#!/bin/bash
# 모든 패널 그래프 생성

cd /home/sslab/mqtt-ebpf-edge/logs/1로그정리

echo "================================================================================"
echo "RL 학습 과정 그래프 생성 (4개 패널 분리)"
echo "================================================================================"

python3 visualize_panel_a_reward.py
python3 visualize_panel_b_p99.py
python3 visualize_panel_c_correlation.py
python3 visualize_panel_d_control.py

echo ""
echo "================================================================================"
echo "✅ 완료!"
echo "================================================================================"
echo ""
ls -lh panel_*.png
echo ""
echo "생성된 파일:"
echo "  - panel_a_reward.png       : (a) 학습 수렴 (보상 증가)"
echo "  - panel_b_rtt_p99.png      : (b) 커널 신호 (RTT ↔ P99)"
echo "  - panel_c_correlation.png  : (c) 버퍼 압력 (snd_ratio ↔ P99)"
echo "  - panel_d_control.png      : (d) 제어 효과 (액션 → 버퍼)"
echo ""
echo "학습 과정 핵심:"
echo "  ✓ 학습이 잘 수렴했는가? → (a)"
echo "  ✓ 커널 신호가 성능과 연관되는가? → (b)"
echo "  ✓ 버퍼 압력이 레이턴시와 연관되는가? → (c)"
echo "  ✓ 제어가 효과적인가? → (d)"
echo ""
