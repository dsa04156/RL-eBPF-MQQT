
import argparse
import json
import numpy as np

try:
    from tqdm import tqdm
except ModuleNotFoundError:
    # tqdm이 없으면 단순 반복자로 대체
    def tqdm(iterable, **_):
        return iterable

def main():
    parser = argparse.ArgumentParser(description='Prepare dataset from JSONL file for behavioral cloning.')
    parser.add_argument('input_file', type=str, help='Path to the input JSONL file.')
    parser.add_argument('--out', type=str, required=True, help='Path to the output .npz file.')
    # Optional filters to select stable/target-band samples
    parser.add_argument('--min_thr', type=float, default=None, help='Minimum throughput (msg/s) = metrics.n / window_sec')
    parser.add_argument('--max_thr', type=float, default=None, help='Maximum throughput (msg/s) = metrics.n / window_sec')
    parser.add_argument('--p99_cap', type=float, default=None, help='Drop samples whose metrics.p99_ms exceeds this (ms)')
    parser.add_argument('--fresh_max', type=float, default=None, help='Drop samples if metrics_fresh_sec exceeds this (s) when present')
    parser.add_argument('--applied_only', action='store_true', help='Keep samples only when record.applied == True (online control applied)')
    args = parser.parse_args()

    states = []
    actions = []

    def pass_filters(entry) -> bool:
        # Robustness: skip non-dict entries
        if not isinstance(entry, dict):
            return False
        # applied filter
        if args.applied_only and not entry.get('applied', False):
            return False

        # metrics-based filters
        m = entry.get('metrics') or {}
        n = m.get('n'); w = m.get('window_sec'); p99 = m.get('p99_ms')

        # throughput band
        if args.min_thr is not None or args.max_thr is not None:
            if not (isinstance(n, (int, float)) and isinstance(w, (int, float)) and w > 0):
                return False
            thr = n / w
            if args.min_thr is not None and thr < args.min_thr:
                return False
            if args.max_thr is not None and thr > args.max_thr:
                return False

        # tail cap
        if args.p99_cap is not None:
            if not isinstance(p99, (int, float)) or p99 > args.p99_cap:
                return False

        # freshness cap (if field exists in logs)
        if args.fresh_max is not None:
            fresh = entry.get('metrics_fresh_sec')
            if isinstance(fresh, (int, float)) and fresh > args.fresh_max:
                return False
        return True

    with open(args.input_file, 'r') as f:
        for line in tqdm(f, desc="Processing logs"):
            try:
                log_entry = json.loads(line)
                # Only accept JSON objects
                if not isinstance(log_entry, dict):
                    continue
                # Apply optional filters
                if not pass_filters(log_entry):
                    continue
                
                # Ensure 's' and 'a' keys exist
                if 's' in log_entry and 'a' in log_entry:
                    states.append(log_entry['s'])
                    
                    action_dict = log_entry['a']
                    # Ensure action dict has the expected keys
                    if 'd_rate' in action_dict and 'd_batch' in action_dict:
                        actions.append([action_dict['d_rate'], action_dict['d_batch']])
                    else:
                        # Potentially handle malformed action entries if necessary
                        # For now, we'll just skip them if they don't match
                        pass
                
            except json.JSONDecodeError:
                print(f"Skipping malformed line: {line.strip()}")

    if not states or not actions:
        print("No valid data found in the input file. Output file will not be created.")
        return

    # Convert lists to numpy arrays
    S_np = np.array(states, dtype=np.float32)
    A_np = np.array(actions, dtype=np.float32)

    # Save to a compressed .npz file
    np.savez_compressed(args.out, S=S_np, A=A_np)

    print(f"Dataset successfully created at {args.out}")
    print(f"Number of samples: {len(S_np)}")
    print(f"S shape: {S_np.shape}")
    print(f"A shape: {A_np.shape}")

if __name__ == '__main__':
    main()
