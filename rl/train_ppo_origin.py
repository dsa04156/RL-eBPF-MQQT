#!/usr/bin/env python3
# train_ppo.py — MQTT eBPF 제어 루프를 대상으로 한 온정책 PPO 학습 스크립트

import argparse
import importlib
import os
import random
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from bcc import BPF
from torch.distributions import Normal

# ---------------------------------------------------------------------------
# eBPF RL 환경 불러오기 (bpf/eda_rl 모듈)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
EDA_RL_DIR = REPO_ROOT / "bpf" / "eda_rl"
EDA_LEGACY_DIR = REPO_ROOT / "bpf"
for path in (EDA_RL_DIR, EDA_LEGACY_DIR):
    if str(path) not in sys.path:
        sys.path.append(str(path))


def _load_rl_impl():
    import sys
    import importlib
    from pathlib import Path
    
    # 1. bpf 디렉토리를 시스템 경로 맨 앞(0번)에 강제 삽입 (최우선 순위 확보)
    # 현재 파일(train_ppo.py)의 상위 상위 폴더 기준 /bpf
    bpf_path = str(Path(__file__).resolve().parents[1] / "bpf")
    
    # 경로 우선순위 조정: bpf 폴더를 맨 위로 올림 (혹시 뒤에 있으면 지우고 앞으로)
    if bpf_path in sys.path:
        sys.path.remove(bpf_path)
    sys.path.insert(0, bpf_path)

    try:
        # 2. eda_rl 모듈 임포트
        import eda_rl
        
        # 3. [핵심] 캐시된 구버전이 메모리에 있다면 무시하고, 파일에서 다시 읽어옴 (Reload)
        importlib.reload(eda_rl)
        
        # 실행 시 터미널에서 어떤 파일을 로드했는지 확인하기 위한 로그
        print(f"[INFO] Force loaded local module: {eda_rl.__file__}")
        
        # legacy 모드(helper 없음)로 리턴
        return eda_rl, "legacy", None
        
    except ImportError as e:
        raise RuntimeError(f"로컬 eda_rl.py를 {bpf_path}에서 찾을 수 없습니다. 에러: {e}")

RL_MODULE, RL_VARIANT, RL_HELPER = _load_rl_impl()
RL = RL_MODULE


def load_bpf_program_legacy():
    if RL.SKIP_EBPF:
        RL._emit("[SKIP] eBPF disabled")
        return None

    program = RL.BPF_PROGRAM.replace("__TRACK_PORT__", str(RL.TRACK_PORT))
    b = BPF(text=program, debug=0x4)
    RL._emit(f"[OK] eBPF loaded for port {RL.TRACK_PORT}")

    ok_send = ok_rcv = True
    try:
        b.attach_kprobe(event="tcp_sendmsg", fn_name="on_tcp_sendmsg")
    except Exception as e:
        ok_send = False
        RL._emit(RL.json.dumps({"warn": "attach_kprobe_sendmsg_failed", "err": str(e)}))

    try:
        b.attach_kprobe(event="tcp_rcv_established", fn_name="on_tcp_rcv_established")
    except Exception as e:
        ok_rcv = False
        RL._emit(RL.json.dumps({"warn": "attach_kprobe_rcv_failed", "err": str(e)}))

    RL._emit(RL.json.dumps({"kprobe_sendmsg": ok_send, "kprobe_rcv": ok_rcv}))
    return b


class ActorCritic(nn.Module):
    """PPO Actor-Critic 네트워크"""

    def __init__(self, state_dim, action_dim, hidden_dim=128):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )
        self.actor_mean = nn.Linear(hidden_dim, action_dim)
        self.actor_log_std = nn.Parameter(torch.zeros(action_dim))
        self.critic = nn.Linear(hidden_dim, 1)

    def forward(self, state):
        features = self.shared(state)
        action_mean = self.actor_mean(features)
        action_std = torch.exp(self.actor_log_std.expand_as(action_mean))
        value = self.critic(features)
        return action_mean, action_std, value

    def get_action(self, state, deterministic=False):
        action_mean, action_std, value = self.forward(state)
        value = value.squeeze(-1)
        if deterministic:
            return action_mean, None, value
        dist = Normal(action_mean, action_std)
        action = dist.sample()
        log_prob = dist.log_prob(action).sum(dim=-1)
        return action, log_prob, value

    def evaluate_actions(self, state, action):
        action_mean, action_std, value = self.forward(state)
        dist = Normal(action_mean, action_std)
        log_prob = dist.log_prob(action).sum(dim=-1)
        entropy = dist.entropy().sum(dim=-1)
        return log_prob, entropy, value.squeeze(-1)


class RolloutBuffer:
    """온정책 샘플 버퍼"""

    def __init__(self, buffer_size, state_dim, action_dim, device):
        self.device = device
        self.buffer_size = buffer_size
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.states = torch.zeros(
            (buffer_size, state_dim), dtype=torch.float32, device=device
        )
        self.actions = torch.zeros(
            (buffer_size, action_dim), dtype=torch.float32, device=device
        )
        self.log_probs = torch.zeros(buffer_size, dtype=torch.float32, device=device)
        self.rewards = torch.zeros(buffer_size, dtype=torch.float32, device=device)
        self.dones = torch.zeros(buffer_size, dtype=torch.float32, device=device)
        self.values = torch.zeros(buffer_size, dtype=torch.float32, device=device)
        self.returns = torch.zeros(buffer_size, dtype=torch.float32, device=device)
        self.advantages = torch.zeros(buffer_size, dtype=torch.float32, device=device)
        self.ptr = 0

    def reset(self):
        self.ptr = 0

    def add(self, state, action, log_prob, reward, done, value):
        if self.ptr >= self.buffer_size:
            raise RuntimeError("RolloutBuffer capacity exceeded")
        self.states[self.ptr].copy_(
            torch.as_tensor(state, dtype=torch.float32, device=self.device)
        )
        self.actions[self.ptr].copy_(
            torch.as_tensor(action, dtype=torch.float32, device=self.device)
        )
        self.log_probs[self.ptr] = float(log_prob)
        self.rewards[self.ptr] = float(reward)
        self.dones[self.ptr] = float(done)
        self.values[self.ptr] = float(value)
        self.ptr += 1

    @property
    def full(self):
        return self.ptr == self.buffer_size

    def set_advantages_returns(self, advantages, returns):
        if advantages.shape != self.advantages.shape or returns.shape != self.returns.shape:
            raise ValueError("Shape mismatch when setting advantages/returns")
        self.advantages.copy_(advantages)
        self.returns.copy_(returns)

    def iter_minibatches(self, batch_size):
        if not self.full:
            raise RuntimeError("Rollout buffer not filled")
        indices = torch.randperm(self.buffer_size, device=self.device)
        for start in range(0, self.buffer_size, batch_size):
            end = start + batch_size
            batch_idx = indices[start:end]
            yield (
                self.states[batch_idx],
                self.actions[batch_idx],
                self.log_probs[batch_idx],
                self.returns[batch_idx],
                self.advantages[batch_idx],
            )


class PPOTrainer:
    def __init__(
        self,
        state_dim,
        action_dim,
        lr=3e-4,
        gamma=0.99,
        gae_lambda=0.95,
        clip_epsilon=0.2,
        value_coef=0.5,
        entropy_coef=0.01,
        max_grad_norm=0.5,
    ):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = ActorCritic(state_dim, action_dim).to(self.device)
        self.optimizer = optim.Adam(self.model.parameters(), lr=lr)
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_epsilon = clip_epsilon
        self.value_coef = value_coef
        self.entropy_coef = entropy_coef
        self.max_grad_norm = max_grad_norm

    def compute_gae(self, rewards, values, dones, last_value):
        """Generalized Advantage Estimation with bootstrap value."""
        values_ext = torch.cat([values, last_value.unsqueeze(0)], dim=0)
        advantages = torch.zeros_like(rewards, device=self.device)
        gae = torch.zeros(1, device=self.device)
        for t in reversed(range(rewards.shape[0])):
            mask = 1.0 - dones[t]
            delta = (
                rewards[t]
                + self.gamma * values_ext[t + 1] * mask
                - values_ext[t]
            )
            gae = delta + self.gamma * self.gae_lambda * mask * gae
            advantages[t] = gae
        returns = advantages + values
        return advantages, returns

    def update(self, buffer, num_epochs=4, batch_size=256):
        advantages = buffer.advantages
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        buffer.advantages.copy_(advantages)

        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        num_updates = 0

        for _ in range(num_epochs):
            for (
                batch_states,
                batch_actions,
                batch_old_log_probs,
                batch_returns,
                batch_advantages,
            ) in buffer.iter_minibatches(batch_size):
                log_probs, entropy, values = self.model.evaluate_actions(
                    batch_states, batch_actions
                )
                ratio = torch.exp(log_probs - batch_old_log_probs)
                surr1 = ratio * batch_advantages
                surr2 = torch.clamp(
                    ratio, 1 - self.clip_epsilon, 1 + self.clip_epsilon
                ) * batch_advantages
                policy_loss = -torch.min(surr1, surr2).mean()

                value_loss = nn.functional.mse_loss(values, batch_returns)
                entropy_loss = -entropy.mean()
                loss = (
                    policy_loss
                    + self.value_coef * value_loss
                    + self.entropy_coef * entropy_loss
                )

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), self.max_grad_norm)
                self.optimizer.step()

                total_policy_loss += policy_loss.item()
                total_value_loss += value_loss.item()
                total_entropy += entropy.mean().item()
                num_updates += 1

        return {
            "policy_loss": total_policy_loss / max(1, num_updates),
            "value_loss": total_value_loss / max(1, num_updates),
            "entropy": total_entropy / max(1, num_updates),
        }

    def save(self, path):
        """TorchScript로 저장 (추론용)"""
        self.model.eval()

        class ActorOnly(nn.Module):
            def __init__(self, actor_critic):
                super().__init__()
                self.shared = actor_critic.shared
                self.actor_mean = actor_critic.actor_mean

            def forward(self, x):
                features = self.shared(x)
                action_mean = self.actor_mean(features)
                action_mean = torch.stack(
                    [
                        torch.clamp(action_mean[:, 0], -0.25, 0.25),
                        torch.clamp(action_mean[:, 1], -1.5, 1.5),
                    ],
                    dim=1,
                )
                return action_mean

        actor_only = ActorOnly(self.model).to(self.device)
        scripted = torch.jit.script(actor_only)
        scripted.save(path)
        print(f"[OK] Saved actor model: {path}")


def build_env(env_mode: str, log_path: str):
    """eBPF + MQTT RL 환경 생성"""
    if RL_VARIANT == "package":
        bpf_obj = RL_HELPER.load_bpf_program()
        mqtt_cli = RL_HELPER.make_mqtt()
    else:
        bpf_obj = load_bpf_program_legacy()
        mqtt_cli = RL.make_mqtt()

    shield = RL.Shield(
        RL.R_MIN,
        RL.R_MAX,
        RL.B_MIN,
        RL.B_MAX,
        RL.MAX_STEP_FRAC,
        RL.COOLDOWN_SEC,
        RL.MAX_DECEL_FRAC,
        RL.DECEL_HOLD_SEC,
    )

    env_kwargs = dict(
        bpf_obj=bpf_obj,
        mqtt_client=mqtt_cli,
        shield=shield,
        mode=env_mode,
        backend="torch",
        log_path=log_path,
        interval_s=RL.INTERVAL_S,
        slo_p99_ms=RL.SLO_P99_MS,
    )
    if RL_VARIANT == "package":
        env_kwargs["latest_metrics"] = RL_HELPER.LATEST_METRICS

    env = RL.MQTTRLGymEnv(**env_kwargs)
    return env, bpf_obj, mqtt_cli


def cleanup_env(env, bpf_obj, mqtt_cli):
    if env is not None:
        try:
            env.close()
        except Exception:
            pass
    if mqtt_cli is not None:
        try:
            mqtt_cli.loop_stop()
            mqtt_cli.disconnect()
        except Exception:
            pass
    if bpf_obj is not None:
        try:
            bpf_obj.cleanup()
        except Exception:
            pass


def collect_rollout(env, trainer, buffer, start_obs):
    obs = start_obs
    rollout_rewards = []
    for _ in range(buffer.buffer_size):
        state_tensor = torch.as_tensor(
            obs, dtype=torch.float32, device=trainer.device
        ).unsqueeze(0)
        with torch.no_grad():
            action_tensor, log_prob_tensor, value_tensor = trainer.model.get_action(
                state_tensor
            )
        action = action_tensor.squeeze(0).cpu().numpy()
        log_prob = log_prob_tensor.squeeze(0).detach()
        value = value_tensor.squeeze(0).detach()

        next_obs, reward, terminated, truncated, _ = env.step(action)
        done = terminated or truncated
        buffer.add(obs, action, log_prob, reward, done, value)
        rollout_rewards.append(reward)
        obs = next_obs

        if done:
            obs, _ = env.reset()
    with torch.no_grad():
        _, _, value_tensor = trainer.model.forward(
            torch.as_tensor(obs, dtype=torch.float32, device=trainer.device).unsqueeze(0)
        )
        last_value = value_tensor.squeeze(-1).squeeze(0)
    return obs, np.mean(rollout_rewards), last_value


def train(args):
    env, bpf_obj, mqtt_cli = build_env(args.env_mode, args.log_path)
    obs, _ = env.reset()

    trainer = PPOTrainer(
        state_dim=env.observation_space.shape[0],
        action_dim=env.action_space.shape[0],
        lr=args.lr,
        gamma=args.gamma,
        gae_lambda=args.gae_lambda,
        clip_epsilon=args.clip_epsilon,
        value_coef=args.value_coef,
        entropy_coef=args.entropy_coef,
        max_grad_norm=args.max_grad_norm,
    )

    buffer = RolloutBuffer(
        buffer_size=args.rollout_steps,
        state_dim=env.observation_space.shape[0],
        action_dim=env.action_space.shape[0],
        device=trainer.device,
    )

    total_updates = max(1, args.total_steps // args.rollout_steps)
    best_reward = -float("inf")
    total_steps = 0

    try:
        for update_idx in range(1, total_updates + 1):
            buffer.reset()
            obs, avg_reward, last_value = collect_rollout(env, trainer, buffer, obs)
            advantages, returns = trainer.compute_gae(
                buffer.rewards, buffer.values, buffer.dones, last_value
            )
            buffer.set_advantages_returns(advantages, returns)
            metrics = trainer.update(
                buffer, num_epochs=args.epochs, batch_size=args.batch_size
            )

            total_steps += buffer.buffer_size
            print(
                f"[Update {update_idx}/{total_updates}] "
                f"steps={total_steps} avg_reward={avg_reward:.3f} "
                f"policy_loss={metrics['policy_loss']:.4f} "
                f"value_loss={metrics['value_loss']:.4f} "
                f"entropy={metrics['entropy']:.4f}"
            )

            if avg_reward > best_reward:
                best_reward = avg_reward
                trainer.save(args.out)
            elif args.save_interval > 0 and update_idx % args.save_interval == 0:
                trainer.save(args.out)
    finally:
        cleanup_env(env, bpf_obj, mqtt_cli)

    print(f"\n[DONE] Total steps: {total_steps}, Best avg reward: {best_reward:.3f}")
    print(
        f"→ 온라인 제어 실행 예시: RL_BACKEND=torch RL_MODE=online RL_MODEL_PATH={args.out} python3 bpf/eda_rl.py"
    )


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "실제 MQTT eBPF 환경과 상호작용하는 온정책 PPO 학습기입니다. "
            "USE_GYM_ENV=1, RL_MODE=online 환경에서 실행해야 합니다."
        )
    )
    ap.add_argument("--out", default="./model_ppo.pt", help="저장할 TorchScript 경로")
    ap.add_argument("--log_path", default=RL.RL_LOG_PATH, help="Env JSONL 로그")
    ap.add_argument(
        "--env_mode",
        choices=["online", "shadow"],
        default="online",
        help="온라인 모드에서만 제어 명령이 실제 적용됩니다.",
    )
    ap.add_argument("--total_steps", type=int, default=4096, help="전체 환경 스텝 수")
    ap.add_argument("--rollout_steps", type=int, default=512, help="업데이트당 샘플 수")
    ap.add_argument("--epochs", type=int, default=4, help="PPO 업데이트 에폭")
    ap.add_argument("--batch_size", type=int, default=256, help="미니배치 크기")
    ap.add_argument("--lr", type=float, default=3e-4, help="Learning rate")
    ap.add_argument("--gamma", type=float, default=0.99, help="Discount factor")
    ap.add_argument("--gae_lambda", type=float, default=0.95, help="GAE lambda")
    ap.add_argument("--clip_epsilon", type=float, default=0.2, help="PPO clip 범위")
    ap.add_argument("--value_coef", type=float, default=0.5, help="Value loss 계수")
    ap.add_argument("--entropy_coef", type=float, default=0.01, help="Entropy 계수")
    ap.add_argument("--max_grad_norm", type=float, default=0.5, help="Gradient clip 한계")
    ap.add_argument(
        "--save_interval",
        type=int,
        default=5,
        help="베스트가 아니더라도 N 업데이트마다 주기 저장 (0=비활성)",
    )
    ap.add_argument("--seed", type=int, default=42, help="난수 시드")
    return ap.parse_args()


def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def main():
    args = parse_args()
    set_seed(args.seed)

    if os.geteuid() != 0 and not RL.SKIP_EBPF:
        print("[WARN] eBPF 로드를 위해 root 권한이 필요할 수 있습니다.")

    if args.rollout_steps <= 0 or args.total_steps <= 0:
        raise ValueError("rollout_steps 및 total_steps는 양수여야 합니다.")
    if args.rollout_steps > args.total_steps:
        raise ValueError("--rollout_steps는 --total_steps 이하여야 합니다.")

    print(
        f"[INFO] Starting PPO training on device "
        f"{torch.device('cuda' if torch.cuda.is_available() else 'cpu')}"
    )
    print(
        f"[INFO] env_mode={args.env_mode}, total_steps={args.total_steps}, "
        f"rollout_steps={args.rollout_steps}, epochs={args.epochs}"
    )

    train(args)


if __name__ == "__main__":
    main()
