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
from torch.distributions import Normal
from bcc import BPF

# ---------------------------------------------------------------------------
# 1. 로컬 eda_rl.py 강제 로드 (환경 설정)
# ---------------------------------------------------------------------------
def _load_rl_impl():
    import sys
    import importlib
    
    # 현재 스크립트(rl/train_ppo.py) 기준 상위 폴더의 bpf/ 경로 찾기
    # 구조: mqtt-ebpf-edge/
    #       ├── bpf/
    #       │   └── eda_rl.py  <-- 이걸 로드해야 함
    #       └── rl/
    #           └── train_ppo.py
    bpf_path = str(Path(__file__).resolve().parents[1] / "bpf")
    
    # 시스템 경로 최우선 순위에 bpf 폴더 추가
    if bpf_path not in sys.path:
        sys.path.insert(0, bpf_path)
    elif sys.path[0] != bpf_path:
        sys.path.remove(bpf_path)
        sys.path.insert(0, bpf_path)

    try:
        import eda_rl
        # 캐시된 구버전 모듈이 있다면 무시하고 파일에서 새로 읽어옴 (Reload)
        importlib.reload(eda_rl)
        print(f"[INFO] Force loaded local module: {eda_rl.__file__}")
        
        # gymnasium 설치 여부 확인 (없으면 클래스가 정의되지 않음)
        if not hasattr(eda_rl, "MQTTRLGymEnv"):
            raise ImportError("eda_rl.py에서 MQTTRLGymEnv를 찾을 수 없습니다. 'pip install gymnasium'을 하셨나요?")
            
        return eda_rl
    except ImportError as e:
        raise RuntimeError(f"로컬 eda_rl.py를 {bpf_path}에서 로드할 수 없습니다.\n원인: {e}")

# 모듈 로드
RL = _load_rl_impl()

def load_bpf_program_legacy():
    """eda_rl 모듈에 정의된 BPF 프로그램을 컴파일하고 로드"""
    if RL.SKIP_EBPF:
        print("[SKIP] eBPF disabled by env var")
        return None
    
    # 트래픽 관찰 포트 주입
    program = RL.BPF_PROGRAM.replace("__TRACK_PORT__", str(RL.TRACK_PORT))
    
    # BPF 로드 (Root 권한 필요)
    b = BPF(text=program)
    
    # 프로브 부착 (실패 시 경고만 출력하고 진행)
    ok_send = ok_rcv = True
    try:
        b.attach_kprobe(event="tcp_sendmsg", fn_name="on_tcp_sendmsg")
    except Exception as e:
        ok_send = False
        print(f"[WARN] attach_kprobe(tcp_sendmsg) failed: {e}")

    try:
        b.attach_kprobe(event="tcp_rcv_established", fn_name="on_tcp_rcv_established")
    except Exception as e:
        ok_rcv = False
        print(f"[WARN] attach_kprobe(tcp_rcv_established) failed: {e}")

    try:
        b.attach_tracepoint(tp="tcp:tcp_retransmit_skb", fn_name="trace_retransmit")
    except Exception:
        pass # tracepoint는 선택사항

    print(f"[INFO] eBPF Probes attached: send={ok_send}, rcv={ok_rcv}")
    return b

# ---------------------------------------------------------------------------
# 2. PPO 알고리즘 (Network & Trainer)
# ---------------------------------------------------------------------------
class ActorCritic(nn.Module):
    def __init__(self, state_dim, action_dim, hidden_dim=128):
        super().__init__()
        # 공통 특징 추출 레이어
        self.shared = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )
        # Actor (행동 결정): 평균(mean)과 표준편차(std) 출력
        self.actor_mean = nn.Linear(hidden_dim, action_dim)
        self.actor_log_std = nn.Parameter(torch.zeros(action_dim))
        
        # Critic (가치 평가): 상태 가치(Value) 출력
        self.critic = nn.Linear(hidden_dim, 1)

    def forward(self, state):
        features = self.shared(state)
        mean = self.actor_mean(features)
        std = torch.exp(self.actor_log_std.expand_as(mean))
        value = self.critic(features)
        return mean, std, value

    def get_action(self, state, deterministic=False):
        """환경 상호작용 시 행동 샘플링"""
        mean, std, value = self.forward(state)
        value = value.squeeze(-1)
        if deterministic:
            return mean, None, value
        
        dist = Normal(mean, std)
        action = dist.sample()
        # 행동 로그 확률 계산 (PPO 업데이트용)
        log_prob = dist.log_prob(action).sum(dim=-1)
        return action, log_prob, value

    def evaluate_actions(self, state, action):
        """학습 시 행동 평가"""
        mean, std, value = self.forward(state)
        dist = Normal(mean, std)
        log_prob = dist.log_prob(action).sum(dim=-1)
        entropy = dist.entropy().sum(dim=-1)
        return log_prob, entropy, value.squeeze(-1)


class RolloutBuffer:
    """PPO 학습 데이터를 저장하는 버퍼"""
    def __init__(self, buffer_size, state_dim, action_dim, device):
        self.device = device
        self.buffer_size = buffer_size
        # 텐서 사전 할당 (속도 최적화)
        self.states = torch.zeros((buffer_size, state_dim), dtype=torch.float32, device=device)
        self.actions = torch.zeros((buffer_size, action_dim), dtype=torch.float32, device=device)
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
            raise RuntimeError("RolloutBuffer is full!")
        self.states[self.ptr] = torch.as_tensor(state, device=self.device)
        self.actions[self.ptr] = torch.as_tensor(action, device=self.device)
        self.log_probs[self.ptr] = float(log_prob)
        self.rewards[self.ptr] = float(reward)
        self.dones[self.ptr] = float(done)
        self.values[self.ptr] = float(value)
        self.ptr += 1

    def compute_gae_and_returns(self, last_value, gamma, gae_lambda):
        """GAE(Generalized Advantage Estimation) 계산"""
        values_ext = torch.cat([self.values, last_value.unsqueeze(0)], dim=0)
        gae = 0
        for t in reversed(range(self.buffer_size)):
            # done이면 다음 가치는 0으로 취급
            mask = 1.0 - self.dones[t]
            delta = self.rewards[t] + gamma * values_ext[t+1] * mask - values_ext[t]
            gae = delta + gamma * gae_lambda * mask * gae
            self.advantages[t] = gae
        self.returns = self.advantages + self.values

    def iter_minibatches(self, batch_size):
        indices = torch.randperm(self.buffer_size, device=self.device)
        for start in range(0, self.buffer_size, batch_size):
            end = start + batch_size
            idx = indices[start:end]
            yield (self.states[idx], self.actions[idx], self.log_probs[idx], 
                   self.returns[idx], self.advantages[idx])


class PPOTrainer:
    def __init__(self, state_dim, action_dim, lr=3e-4, device="cpu"):
        self.device = device
        self.model = ActorCritic(state_dim, action_dim).to(device)
        self.optimizer = optim.Adam(self.model.parameters(), lr=lr)
        # PPO 하이퍼파라미터
        self.clip_epsilon = 0.2
        self.value_coef = 0.5
        self.entropy_coef = 0.01
        self.max_grad_norm = 0.5

    def update(self, buffer, num_epochs=4, batch_size=64):
        # Advantage Normalization (학습 안정성)
        adv = buffer.advantages
        buffer.advantages = (adv - adv.mean()) / (adv.std() + 1e-8)

        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        num_updates = 0

        for _ in range(num_epochs):
            for s, a, old_log_p, ret, adv in buffer.iter_minibatches(batch_size):
                log_p, entropy, val = self.model.evaluate_actions(s, a)
                
                # PPO Ratio & Clipping
                ratio = torch.exp(log_p - old_log_p)
                surr1 = ratio * adv
                surr2 = torch.clamp(ratio, 1.0 - self.clip_epsilon, 1.0 + self.clip_epsilon) * adv
                
                loss_p = -torch.min(surr1, surr2).mean()
                loss_v = 0.5 * ((val - ret) ** 2).mean()
                loss_e = -entropy.mean()
                
                loss = loss_p + self.value_coef * loss_v + self.entropy_coef * loss_e
                
                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), self.max_grad_norm)
                self.optimizer.step()

                total_policy_loss += loss_p.item()
                total_value_loss += loss_v.item()
                total_entropy += entropy.mean().item()
                num_updates += 1

        return {
            "policy_loss": total_policy_loss / max(1, num_updates),
            "value_loss": total_value_loss / max(1, num_updates),
            "entropy": total_entropy / max(1, num_updates),
        }

    def save_checkpoint(self, path):
        """재학습용 체크포인트 저장 (.ckpt)"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save({
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
        }, path)
        print(f"[SAVED] Checkpoint: {path}")

    def load_checkpoint(self, path):
        """재학습용 체크포인트 로드"""
        if not os.path.exists(path):
            print(f"[WARN] Checkpoint file not found: {path}")
            return
        checkpoint = torch.load(path, map_location=self.device)
        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        print(f"[LOADED] Resumed training from: {path}")

    def save_inference_model(self, path):
        """실행(Inference)용 경량 모델 저장 (.pt)"""
        class ActorOnly(nn.Module):
            def __init__(self, ac):
                super().__init__()
                self.shared = ac.shared
                self.actor_mean = ac.actor_mean
            def forward(self, x):
                f = self.shared(x)
                a = self.actor_mean(f)
                # 출력값 클램핑 (안전장치)
                # rate: -0.25 ~ 0.25, batch: -1.5 ~ 1.5 (대략 -1, 0, 1)
                return torch.stack([
                    torch.clamp(a[:, 0], -0.25, 0.25), 
                    torch.clamp(a[:, 1], -1.5, 1.5)
                ], dim=1)
        
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.model.eval()
        actor = ActorOnly(self.model).to("cpu")
        # TorchScript로 변환하여 저장 (C++ 등에서도 로드 가능)
        scripted = torch.jit.script(actor)
        scripted.save(path)
        self.model.to(self.device) # 다시 원위치
        print(f"[SAVED] Inference Model: {path}")


# ---------------------------------------------------------------------------
# 3. 학습 파이프라인 (Environment Build & Loop)
# ---------------------------------------------------------------------------
def build_env(env_mode: str, log_path: str):
    # BPF 및 MQTT 클라이언트 생성
    bpf_obj = load_bpf_program_legacy()
    mqtt_cli = RL.make_mqtt()
    
    # Shield(안전장치) 생성
    shield = RL.Shield(
        RL.R_MIN, RL.R_MAX, RL.B_MIN, RL.B_MAX, 
        RL.MAX_STEP_FRAC, RL.COOLDOWN_SEC, RL.MAX_DECEL_FRAC, RL.DECEL_HOLD_SEC
    )
    
    # Gym 환경 생성
    env_kwargs = dict(
        bpf_obj=bpf_obj, mqtt_client=mqtt_cli, shield=shield,
        mode=env_mode, backend="torch", log_path=log_path,
        interval_s=RL.INTERVAL_S, slo_p99_ms=RL.SLO_P99_MS
    )
    
    # eda_rl.py에 정의된 MQTTRLGymEnv 클래스 사용
    env = RL.MQTTRLGymEnv(**env_kwargs)
    return env, bpf_obj, mqtt_cli


def cleanup_env(env, bpf_obj, mqtt_cli):
    """종료 시 리소스 정리"""
    if env: 
        try: env.close() 
        except: pass
    if mqtt_cli: 
        try: mqtt_cli.loop_stop(); mqtt_cli.disconnect()
        except: pass
    if bpf_obj: 
        try: bpf_obj.cleanup()
        except: pass


def collect_rollout(env, trainer, buffer, start_obs):
    """환경과 상호작용하며 데이터 수집 (Rollout)"""
    obs = start_obs
    rollout_rewards = []
    
    for _ in range(buffer.buffer_size):
        # 1. 행동 결정
        state_t = torch.as_tensor(obs, dtype=torch.float32, device=trainer.device).unsqueeze(0)
        with torch.no_grad():
            action_t, log_prob_t, value_t = trainer.model.get_action(state_t)
        
        # 2. 환경에 적용 (Step)
        action = action_t.cpu().numpy()[0]
        next_obs, reward, term, trunc, _ = env.step(action)
        done = term or trunc
        
        # 3. 버퍼에 저장
        buffer.add(obs, action, log_prob_t, reward, done, value_t)
        rollout_rewards.append(reward)
        obs = next_obs
        
        if done: 
            obs, _ = env.reset()

    # 마지막 상태 가치 계산 (Bootstrapping용)
    with torch.no_grad():
        state_t = torch.as_tensor(obs, dtype=torch.float32, device=trainer.device).unsqueeze(0)
        _, _, next_val = trainer.model.get_action(state_t)
        
    return obs, np.mean(rollout_rewards), next_val.squeeze(0)


def train(args):
    # 1. 환경 및 모델 준비
    env, bpf_obj, mqtt_cli = build_env(args.env_mode, args.log_path)
    obs, _ = env.reset()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    state_dim = env.observation_space.shape[0]
    action_dim = env.action_space.shape[0]
    
    trainer = PPOTrainer(state_dim, action_dim, lr=args.lr, device=device)

    # 2. 이어하기 (Resume) 확인
    if args.resume:
        trainer.load_checkpoint(args.resume)

    buffer = RolloutBuffer(args.rollout_steps, state_dim, action_dim, device)
    
    total_updates = max(1, args.total_steps // args.rollout_steps)
    best_reward = -float("inf")
    total_steps = 0

    print(f"\n[INFO] Start Training on {device}")
    print(f"       Total Steps: {args.total_steps}")
    print(f"       Rollout Steps: {args.rollout_steps}")
    print(f"       Resume: {args.resume if args.resume else 'No'}")
    print("---------------------------------------------------------------")

    try:
        for update_idx in range(1, total_updates + 1):
            buffer.reset()
            
            # 3. 데이터 수집 (Interaction)
            # 여기서 env.step()이 호출되며 실제 제어가 일어납니다.
            obs, avg_reward, last_value = collect_rollout(env, trainer, buffer, obs)
            
            # 4. 학습 (Update)
            buffer.compute_gae_and_returns(last_value, args.gamma, args.gae_lambda)
            metrics = trainer.update(buffer, args.epochs, args.batch_size)

            total_steps += buffer.buffer_size
            print(f"[Update {update_idx}/{total_updates}] Step {total_steps}: Avg Reward={avg_reward:.3f} | "
                  f"Loss(P/V/E)={metrics['policy_loss']:.3f}/{metrics['value_loss']:.3f}/{metrics['entropy']:.3f}")

            # 5. 저장 (Save)
            if update_idx % args.save_interval == 0:
                ckpt_path = args.out.replace(".pt", ".ckpt")
                trainer.save_checkpoint(ckpt_path)
                trainer.save_inference_model(args.out)
                
            if avg_reward > best_reward:
                best_reward = avg_reward
                # Best 모델 별도 저장 (선택사항)
                # trainer.save_inference_model(args.out.replace(".pt", "_best.pt"))

    except KeyboardInterrupt:
        print("\n[STOP] User interrupted training.")
    finally:
        cleanup_env(env, bpf_obj, mqtt_cli)

    # 종료 전 최종 저장
    ckpt_path = args.out.replace(".pt", ".ckpt")
    trainer.save_checkpoint(ckpt_path)
    trainer.save_inference_model(args.out)
    print(f"[DONE] Training Finished. Best Reward: {best_reward:.3f}")


def parse_args():
    ap = argparse.ArgumentParser(description="PPO Trainer for MQTT-eBPF")
    ap.add_argument("--out", default="./models/ppo_model.pt", help="Output model path (.pt)")
    ap.add_argument("--log_path", default=RL.RL_LOG_PATH, help="Training log JSONL path")
    ap.add_argument("--env_mode", default="online", choices=["online", "shadow"])
    ap.add_argument("--total_steps", type=int, default=4096)
    ap.add_argument("--rollout_steps", type=int, default=512)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch_size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--gamma", type=float, default=0.99)
    ap.add_argument("--gae_lambda", type=float, default=0.95)
    ap.add_argument("--save_interval", type=int, default=5, help="Save every N updates")
    ap.add_argument("--seed", type=int, default=42)
    
    # [Resume 옵션]
    ap.add_argument("--resume", type=str, default="", help="Path to .ckpt file to resume training")
    
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
    
    # Root 권한 체크
    if os.geteuid() != 0 and not RL.SKIP_EBPF:
        print("[WARN] eBPF 로드를 위해 root 권한이 필요할 수 있습니다 (sudo).")
        
    train(args)

if __name__ == "__main__":
    main()