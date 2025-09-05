#!/bin/bash
# LHS 기반 마스터 실험 실행 스크립트
echo "🚀 LHS 샘플링 200개 실험 런 시작"

for i in {1..200}; do
    echo "📊 LHS 실험 $i/200 실행 중..."
    ./experiment_scripts/run_$i.sh
    
    if [ $? -eq 0 ]; then
        echo "✅ 실험 $i 성공"
    else
        echo "❌ 실험 $i 실패"
    fi
    
    # 서버 간 쿨다운
    echo "😴 30초 쿨다운..."
    sleep 30
done

echo "🎉 모든 LHS 실험 완료!"
