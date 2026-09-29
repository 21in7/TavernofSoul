cd /home/temperantia/TavernofSoul/
source /home/temperantia/TavernofSoul/TavernofSoul/itos/3.8/bin/activate
# ========== downloading patch ipf ========
cd downloader
python downloader.py ktest
cd ..
# ========== unpacking ipf ========
# python unpackIPF.py ktest
# ========== parsing unpacked ipf ========
cd parser_tidy
source /home/temperantia/TavernofSoul/py27/bin/activate
python map_image.py ktest
source /home/temperantia/TavernofSoul/TavernofSoul/itos/3.8/bin/activate
python main.py ktest
parse_result=$?
# 안전장치: parser 가 실패하면 부분 결과를 DB 로 import 하지 않고 중단.
if [ $parse_result -ne 0 ]; then
    echo "KTEST 데이터 파싱 실패(return code $parse_result). import 중단." >> ../err.txt
    exit 1
fi
# ========== importing changes to DB ========
cd ..
cd TavernofSoul
python manage_ktest.py importAll >> ../err.txt
import_result=$?
# DB 적재 실패를 성공한 업데이트로 기록하지 않는다.
if [ "$import_result" -ne 0 ]; then
    echo "DB import 실패(return code $import_result). 업데이트 중단." >&2
    exit "$import_result"
fi
cd ..
python closer.py ktest
