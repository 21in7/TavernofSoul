cd /home/temperantia/TavernofSoul/
source /home/temperantia/TavernofSoul/TavernofSoul/itos/3.8/bin/activate
# ========== downloading patch ipf ========
cd downloader
python downloader.py twtos
cd ..
# ========== unpacking ipf ========
# python unpackIPF.py itos  # included in downloader
# ========== parsing unpacked ipf ========
cd parser_tidy
source /home/temperantia/TavernofSoul/py27/bin/activate
python map_image.py twtos
source /home/temperantia/TavernofSoul/TavernofSoul/itos/3.8/bin/activate
python main.py twtos
parse_result=$?
# 안전장치: parser 가 실패하면 부분 결과를 DB 로 import 하지 않고 중단.
if [ $parse_result -ne 0 ]; then
    echo "TWTOS 데이터 파싱 실패(return code $parse_result). import 중단." >> ../err.txt
    exit 1
fi
# ========== importing changes to DB ========
cd ..
cd TavernofSoul
python manage_twtos.py importAll >> ../err.txt
cd ..
python closer.py twtos
