#!/usr/bin/env python3
"""
논문 PDF에서 핵심 내용 추출
연구 목적, 기존 연구 한계, 제안 방법의 차별점 확인
"""

import PyPDF2
import re

pdf_path = "KNUthesisformat (3).pdf"

print("=" * 80)
print("📄 논문 내용 분석: 연구의 핵심 차별점 찾기")
print("=" * 80)

try:
    with open(pdf_path, 'rb') as f:
        pdf = PyPDF2.PdfReader(f)
        
        print(f"\n총 페이지 수: {len(pdf.pages)}")
        
        # 각 섹션별로 찾기
        sections = {
            '서론/목적': ['목적', '배경', 'motivation', 'introduction', '서론'],
            '기존연구': ['관련', 'related', '기존', '선행', 'prior'],
            'TCP/혼잡제어': ['TCP', 'congestion', '혼잡', 'flow control'],
            '제안방법': ['제안', 'proposed', 'approach', '방법론', 'methodology'],
            '차별점': ['차별', '기여', 'contribution', 'novelty', '한계']
        }
        
        findings = {key: [] for key in sections.keys()}
        
        # 처음 50페이지 스캔
        for i in range(min(50, len(pdf.pages))):
            try:
                page = pdf.pages[i]
                text = page.extract_text()
                
                if not text:
                    continue
                
                # 각 섹션 키워드 체크
                for section_name, keywords in sections.items():
                    if any(k.lower() in text.lower() for k in keywords):
                        findings[section_name].append({
                            'page': i + 1,
                            'text': text[:800]  # 처음 800자
                        })
            except Exception as e:
                continue
        
        # 결과 출력
        print("\n" + "=" * 80)
        print("📊 발견된 내용 요약")
        print("=" * 80)
        
        for section_name, pages in findings.items():
            if pages:
                print(f"\n🔍 [{section_name}] 관련 내용 ({len(pages)} 페이지)")
                print("-" * 80)
                
                # 처음 2개 페이지만 상세 출력
                for idx, item in enumerate(pages[:2]):
                    print(f"\n--- Page {item['page']} ---")
                    
                    # 텍스트 정리 (줄바꿈, 공백 정리)
                    text = item['text']
                    text = re.sub(r'\s+', ' ', text)
                    text = text[:600]  # 600자로 제한
                    
                    print(text)
                    print()
                
                if len(pages) > 2:
                    print(f"... 외 {len(pages) - 2}개 페이지 더 있음")
        
        # 핵심 키워드 빈도 분석
        print("\n" + "=" * 80)
        print("🔑 핵심 키워드 빈도 (전체 50페이지)")
        print("=" * 80)
        
        all_text = ""
        for i in range(min(50, len(pdf.pages))):
            try:
                text = pdf.pages[i].extract_text()
                if text:
                    all_text += text.lower()
            except:
                continue
        
        keywords_to_check = {
            'TCP': ['tcp', 'transmission control'],
            '혼잡제어': ['congestion control', '혼잡 제어', 'cwnd'],
            'eBPF': ['ebpf', 'bpf'],
            'MQTT': ['mqtt', 'message queue'],
            'RL/강화학습': ['reinforcement learning', '강화학습', 'rl'],
            'Tail Latency': ['tail latency', 'p99', 'p95'],
            'Flow Control': ['flow control', 'rate control', 'rate limiting'],
            'Edge': ['edge', '엣지'],
            'SLO': ['slo', 'service level']
        }
        
        for category, terms in keywords_to_check.items():
            count = sum(all_text.count(term) for term in terms)
            print(f"{category:<20}: {count:>3}회")
        
        # 초록 찾기
        print("\n" + "=" * 80)
        print("📝 초록 (Abstract) 찾기")
        print("=" * 80)
        
        for i in range(min(10, len(pdf.pages))):
            try:
                text = pdf.pages[i].extract_text()
                if text and ('초록' in text or 'abstract' in text.lower()):
                    print(f"\n--- Page {i+1} ---")
                    # 초록 부분만 추출
                    lines = text.split('\n')
                    in_abstract = False
                    abstract_lines = []
                    
                    for line in lines:
                        if '초록' in line or 'abstract' in line.lower():
                            in_abstract = True
                            continue
                        if in_abstract:
                            if len(line.strip()) > 10:
                                abstract_lines.append(line.strip())
                            if len(abstract_lines) > 15:  # 적당한 길이
                                break
                    
                    print('\n'.join(abstract_lines[:15]))
                    break
            except:
                continue

except FileNotFoundError:
    print(f"\n❌ 파일을 찾을 수 없습니다: {pdf_path}")
    print("현재 디렉토리를 확인하세요.")
except Exception as e:
    print(f"\n❌ 오류 발생: {e}")

print("\n" + "=" * 80)
print("✅ 분석 완료")
print("=" * 80)
