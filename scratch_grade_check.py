import sys, os, re

dump_files = sorted([f for f in os.listdir('logs') if f.startswith('seat_iframe') and f.endswith('.html')])
latest = dump_files[-1]
print(f"분석 파일: {latest}")

try:
    with open(f'logs/{latest}', 'r', encoding='utf-16') as f:
        html = f.read()
except:
    with open(f'logs/{latest}', 'r', encoding='utf-16le', errors='ignore') as f:
        html = f.read()

# SportsSeatGradeList_contentItem 분석
print("\n=== SportsSeatGradeList_contentItem 요소 ===")
items = re.findall(r'<div[^>]*class="[^"]*SportsSeatGradeList_contentItem[^"]*"[^>]*>.*?</div>\s*</div>', html, re.DOTALL)
print(f"발견 개수: {len(items)}")
for item in items[:5]:
    clean = re.sub(r'<[^>]+>', ' ', item)
    clean = ' '.join(clean.split())
    print(f"  [{clean[:150]}]")

# LI 요소의 data 속성 확인
print("\n=== SeatGradeLayer_item 전체 태그 ===")
lis = re.findall(r'<li[^>]*SeatGradeLayer_item[^>]*>', html)
print(f"발견 개수: {len(lis)}")
for li in lis[:5]:
    print(f"  {li[:200]}")

# active/disabled 상태 확인
print("\n=== active/disabled 클래스 포함된 LI ===")
for li in lis[:35]:
    if 'active' in li.lower() or 'disabled' in li.lower() or 'selected' in li.lower():
        print(f"  STATE: {li[:200]}")

# 잔여석 카운트 형식
print("\n=== 잔여석(remainCount) 포함 텍스트 ===")
remain = re.findall(r'<[^>]*RemainCount[^>]*>(.*?)</', html, re.DOTALL)
for r in remain[:10]:
    print(f"  {r.strip()}")

# button 역할 요소 분석
print("\n=== SeatGradeLayer button 요소 ===")
btns = re.findall(r'<(?:button|div|li)[^>]*class="[^"]*SeatGradeLayer_(?:toggleButton|grade)[^"]*"[^>]*>', html)
print(f"발견 개수: {len(btns)}")
for btn in btns[:10]:
    print(f"  {btn[:200]}")
