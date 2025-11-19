#!/usr/bin/env python3
"""
재전송 횟수를 수치로 표시하는 스크립트
"""
import json
import sys

def main():
    log_file = sys.argv[1] if len(sys.argv) > 1 else "logs/torch_model_experiments/test.jsonl"
    
    print(f"📊 재전송 횟수 분석: {log_file}\n")
    print("=" * 80)
    
    total_lines = 0
    total_retrans = 0
    max_retrans = 0
    lines_with_retrans = 0
    retrans_values = []
    
    with open(log_file, 'r') as f:
        for line in f:
            if not line.strip():
                continue
            
            total_lines += 1
            data = json.loads(line)
            kernel = data.get('kernel', {})
            
            # retrans_count 필드 확인
            if 'retrans_count' in kernel:
                count = kernel['retrans_count']
                retrans_values.append(count)
                total_retrans += count
                if count > 0:
                    lines_with_retrans += 1
                if count > max_retrans:
                    max_retrans = count
                
                # 샘플 출력 (처음 5개)
                if total_lines <= 5:
                    ts = data.get('ts', 0)
                    had = kernel.get('had_retrans', False)
                    print(f"Line {total_lines}: ts={ts:.2f}, had_retrans={had}, retrans_count={count}")
            else:
                # retrans_count 필드가 없으면 had_retrans만 표시
                had = kernel.get('had_retrans', False)
                if total_lines <= 5:
                    ts = data.get('ts', 0)
                    print(f"Line {total_lines}: ts={ts:.2f}, had_retrans={had}, retrans_count=N/A ⚠️")
    
    print("\n" + "=" * 80)
    print(f"\n📈 통계 요약:")
    print(f"  총 라인 수: {total_lines}")
    print(f"  총 재전송 횟수: {total_retrans}")
    print(f"  재전송 발생 라인: {lines_with_retrans} ({lines_with_retrans/max(1,total_lines)*100:.1f}%)")
    print(f"  최대 재전송 (한 번에): {max_retrans}")
    
    if retrans_values:
        avg = sum(retrans_values) / len(retrans_values)
        print(f"  평균 재전송 (라인당): {avg:.2f}")
        print(f"\n✅ retrans_count 필드 있음 - 수치로 측정 가능!")
    else:
        print(f"\n⚠️  retrans_count 필드 없음 - boolean만 있음!")
        print(f"  → bpf/eda_rl.py를 다시 실행해야 합니다")

if __name__ == "__main__":
    main()
