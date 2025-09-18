#!/usr/bin/env python3
# train_bc.py — Behavior Cloning 학습 (S->A 회귀), TorchScript로 저장
import argparse, numpy as np, torch, torch.nn as nn, torch.optim as optim

class MLP(nn.Module):
    def __init__(self, in_dim, out_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 128), nn.ReLU(),
            nn.Linear(128, 128), nn.ReLU(),
            nn.Linear(128, out_dim)
        )
    def forward(self, x): return self.net(x)

def clamp_(x, lo, hi): return torch.clamp(x, lo, hi)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="./dataset.npz")
    ap.add_argument("--out",  default="./model_bc.pt")
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--bs",     type=int, default=1024)
    ap.add_argument("--lr",     type=float, default=3e-4)
    ap.add_argument("--val_split", type=float, default=0.1)
    args = ap.parse_args()

    D = np.load(args.data)
    S = torch.tensor(D["S"], dtype=torch.float32)
    A = torch.tensor(D["A"], dtype=torch.float32)
    N, in_dim = S.shape; out_dim = A.shape[1]
    n_val = int(N * args.val_split)
    idx = torch.randperm(N)
    val_idx, tr_idx = idx[:n_val], idx[n_val:]
    S_tr, A_tr = S[tr_idx], A[tr_idx]
    S_val, A_val = S[val_idx], A[val_idx]

    model = MLP(in_dim, out_dim)
    opt   = optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.SmoothL1Loss()

    def run_epoch(split):
        model.train(split=="train")
        X = S_tr if split=="train" else S_val
        Y = A_tr if split=="train" else A_val
        bs = args.bs if split=="train" else min(args.bs, len(X))
        loader = torch.utils.data.DataLoader(
            torch.utils.data.TensorDataset(X, Y),
            batch_size=bs, shuffle=(split=="train"))
        tot = 0.0
        with torch.set_grad_enabled(split=="train"):
            for s,a in loader:
                pred = model(s)                # [N,2]  = [d_rate_frac, d_batch_step]
                # 출력 안전 클램프(훈련 안정)
                pred = torch.stack([clamp_(pred[:,0], -0.25, 0.25),
                                    clamp_(pred[:,1], -1.5,  1.5)], dim=1)
                loss = loss_fn(pred, a)
                if split=="train":
                    opt.zero_grad(); loss.backward(); opt.step()
                tot += loss.item()*len(s)
        return tot/len(X)

    best = float("inf"); best_state=None
    for ep in range(1, args.epochs+1):
        tr = run_epoch("train"); va = run_epoch("val")
        print(f"[ep {ep:02d}] train={tr:.6f}  val={va:.6f}")
        if va < best:
            best = va
            best_state = {k: v.cpu().clone() for k,v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    # TorchScript로 저장
    model.eval()
    scripted = torch.jit.script(model)
    scripted.save(args.out)
    print(f"[OK] saved model: {args.out}  (val_loss={best:.6f})")
    print("→ eda_rl.py 실행 시: RL_BACKEND=torch, RL_MODEL_PATH=./model_bc.pt 로 설정")

if __name__ == "__main__":
    main()