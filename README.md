# Hospital 데이터 검증 가이드

## 1. 전체 통계
```sql
SELECT 
    COUNT(*) as 전체,
    COUNT(region_category_id) as 매핑완료,
    COUNT(*) - COUNT(region_category_id) as 미매핑,
    ROUND(COUNT(region_category_id)::numeric / COUNT(*) * 100, 2) as 매핑률
FROM hospital_temp;
```

**기대값:** 매핑률 99% 이상

---

## 2. 미매핑 데이터 상세
```sql
SELECT sido, sigungu, COUNT(*) as 건수
FROM hospital_temp
WHERE region_category_id IS NULL
  AND sido IS NOT NULL AND sido != '' AND sido != 'nan'
GROUP BY sido, sigungu
ORDER BY COUNT(*) DESC
LIMIT 30;
```

**조치:** 미매핑 건수가 많으면 `region_category` 테이블에 해당 시군구 추가 필요

---

## 3. 시도별 통계
```sql
SELECT 
    sido,
    COUNT(*) as 전체,
    COUNT(region_category_id) as 매핑,
    COUNT(*) - COUNT(region_category_id) as 미매핑
FROM hospital_temp
WHERE sido IS NOT NULL AND sido != ''
GROUP BY sido
ORDER BY COUNT(*) DESC;
```

---

## 4. 빈 주소 데이터 확인
```sql
SELECT COUNT(*) as 빈주소_건수
FROM hospital_temp
WHERE (sido IS NULL OR sido = '' OR sido = 'nan')
   OR (sigungu IS NULL OR sigungu = '');
```

**참고:** 공공데이터 원본에 주소가 없는 경우 발생

---

## 5. 업종별 통계
```sql
SELECT 
    hospital_type,
    COUNT(*) as 건수
FROM hospital_temp
GROUP BY hospital_type
ORDER BY COUNT(*) DESC;
```

---

## 6. region_category에 없는 시군구 확인
```sql
SELECT DISTINCT ht.sido, ht.sigungu
FROM hospital_temp ht
LEFT JOIN region_category rc ON rc.name = ht.sigungu 
    AND rc.depth = 2 
    AND rc.deleted = false
WHERE ht.region_category_id IS NULL
  AND ht.sido IS NOT NULL AND ht.sido != '' AND ht.sido != 'nan'
  AND ht.sigungu IS NOT NULL AND ht.sigungu != ''
  AND rc.id IS NULL
ORDER BY ht.sido, ht.sigungu;
```

**조치:** 결과가 있으면 `region_category` 테이블에 추가 필요
```sql
-- 추가 예시 (ID는 MAX(id) + 1로 조정)
INSERT INTO region_category (id, created_at, modified_at, deleted, depth, id_path, name, name_path, parent_id)
VALUES (9999, NOW(), NOW(), false, 2, '1|2|{parent_id}|9999', '{시군구명}', 'REGION|ADDRESS|{시도명}|{시군구명}', {parent_id});
```

---

## 7. 최근 데이터 샘플 확인
```sql
SELECT name, sido, sigungu, road_address, hospital_type, region_category_id
FROM hospital_temp
ORDER BY license_date DESC NULLS LAST
LIMIT 20;
```

---

## 검증 체크리스트

| 항목 | 기준 | 조치 |
|------|------|------|
| 매핑률 | 99% 이상 | 미달 시 미매핑 데이터 분석 |
| 미매핑 시군구 | 0건 | region_category 추가 |
| 빈 주소 | 최소화 | 공공데이터 원본 문제 (무시 가능) |
| 전체 건수 | 약 80,000건 | 급격한 변동 시 스크래핑 확인 |