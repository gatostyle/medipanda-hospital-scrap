import os
import json
import requests

API_URL = os.environ.get("API_URL")
INPUT_FILE = "hospital_data.json"

def main():
    print("=" * 60)
    print(f"📤 API 전송 (URL: {API_URL})")
    print("=" * 60)

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"📄 {len(data):,}건 로드")

    # 1. 기존 데이터 삭제
    print("\n🗑️ 기존 데이터 삭제 중...")
    response = requests.delete(
        f"{API_URL}/v1/hospitals/all",
        timeout=60
    )
    response.raise_for_status()
    print("✅ 삭제 완료")

    # 2. 배치로 삽입
    batch_size = 1000
    total_batches = (len(data) + batch_size - 1) // batch_size

    print(f"\n📤 데이터 전송 중... ({total_batches}배치)")

    for i in range(0, len(data), batch_size):
        batch = data[i:i + batch_size]
        batch_num = i // batch_size + 1

        try:
            response = requests.post(
                f"{API_URL}/v1/hospitals/bulk-upsert",
                json=batch,
                headers={"Content-Type": "application/json"},
                timeout=120
            )
            response.raise_for_status()
            result = response.json()
            print(f"   배치 {batch_num}/{total_batches}: {result.get('inserted', len(batch))}건")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ 배치 {batch_num} 실패: {e}")
            raise

    print("\n" + "=" * 60)
    print("✅ 전송 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()