#!/usr/bin/env python3
"""
논문에서 핵심 차별점을 더 자세히 추출하는 스크립트
"""
import sys
import re
import PyPDF2

def extract_pages(pdf_path, start_page, end_page):
    """특정 페이지 범위의 텍스트를 추출"""
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page_num in range(start_page-1, min(end_page, len(reader.pages))):
                page = reader.pages[page_num]
                text += f"\n=== Page {page_num+1} ===\n"
                text += page.extract_text()
            return text
    except Exception as e:
        return f"Error: {e}"

def find_section(pdf_path, section_keywords):
    """특정 키워드가 포함된 섹션 찾기"""
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            results = []
            for page_num, page in enumerate(reader.pages, start=1):
                text = page.extract_text()
                for keyword in section_keywords:
                    if keyword.lower() in text.lower():
                        results.append({
                            'page': page_num,
                            'keyword': keyword,
                            'snippet': text[:1000]  # 처음 1000자
                        })
                        break
            return results
    except Exception as e:
        return [{'error': str(e)}]

def main():
    pdf_path = "KNUthesisformat (3).pdf"
    
    print("="*80)
    print("📄 논문 상세 내용 분석")
    print("="*80)
    
    # 1. 서론 부분 (연구 배경, 문제 정의, 목표)
    print("\n🎯 1. 서론 (연구 배경, 문제 정의, 목표)")
    print("-"*80)
    intro_text = extract_pages(pdf_path, 9, 14)  # 대략 서론 페이지
    print(intro_text[:3000])  # 처음 3000자
    
    # 2. 관련 연구 부분 (기존 방법론과 한계)
    print("\n\n📚 2. 관련 연구 (기존 방법론과 한계)")
    print("-"*80)
    related_text = extract_pages(pdf_path, 13, 18)  # 대략 관련 연구 페이지
    print(related_text[:3000])
    
    # 3. 제안 방법 (eMQTT-RL의 차별점)
    print("\n\n💡 3. 제안 방법 (eMQTT-RL의 차별점)")
    print("-"*80)
    method_text = extract_pages(pdf_path, 18, 30)  # 대략 제안 방법 페이지
    print(method_text[:4000])
    
    # 4. 실험 결과 (베이스라인과의 비교)
    print("\n\n📊 4. 실험 결과 찾기")
    print("-"*80)
    results = find_section(pdf_path, [
        "baseline", "베이스라인", "비교", "성능평가", 
        "실험결과", "EMQX", "제어없음", "no control"
    ])
    for r in results[:5]:
        if 'error' in r:
            print(f"Error: {r['error']}")
        else:
            print(f"\n--- Page {r['page']}: {r['keyword']} ---")
            print(r['snippet'][:800])
    
    # 5. 기여/차별점 명시 부분
    print("\n\n🔑 5. 본 연구의 기여 (Contribution)")
    print("-"*80)
    contrib_results = find_section(pdf_path, [
        "기여", "contribution", "차별", "differentiation", 
        "novelty", "비침투적", "non-intrusive"
    ])
    for r in contrib_results[:3]:
        if 'error' in r:
            print(f"Error: {r['error']}")
        else:
            print(f"\n--- Page {r['page']}: {r['keyword']} ---")
            print(r['snippet'][:1000])
    
    # 6. TCP 혼잡 제어와의 비교 부분
    print("\n\n🔬 6. TCP 혼잡 제어 vs 제안 방법")
    print("-"*80)
    tcp_results = find_section(pdf_path, [
        "TCP 혼잡", "congestion control", "TCP와", "커널 버퍼",
        "send buffer", "application layer", "응용 계층"
    ])
    for r in tcp_results[:3]:
        if 'error' in r:
            print(f"Error: {r['error']}")
        else:
            print(f"\n--- Page {r['page']}: {r['keyword']} ---")
            print(r['snippet'][:1000])
    
    print("\n" + "="*80)
    print("✅ 분석 완료")
    print("="*80)

if __name__ == "__main__":
    main()
