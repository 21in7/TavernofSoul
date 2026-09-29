# -*- coding: utf-8 -*-
"""
Challenge Mode Auto Map IES 파일을 파싱하여 DB에 저장하는 Management Command

사용법:
    python manage.py importChallengeModeAutoMap --file ktos_unpack/ies.ipf/challenge_mode_auto_map.ies
    python manage.py importChallengeModeAutoMap --file ktos_unpack/ies.ipf/challenge_mode_auto_map.ies --update
"""

from django.core.management.base import BaseCommand
from django.conf import settings
import logging
import csv
import io
from os.path import join, exists
from pathlib import Path
from Challenge.models import ChallengeModeAutoMap

class Command(BaseCommand):
    help = 'IES 파일을 파싱하여 ChallengeModeAutoMap 모델에 저장합니다'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            help='IES 파일 경로 (기본값: ktos_unpack/ies.ipf/challenge_mode_auto_map.ies)',
            default='ktos_unpack/ies.ipf/challenge_mode_auto_map.ies'
        )
        parser.add_argument(
            '--update',
            action='store_true',
            help='기존 데이터를 업데이트합니다 (기본값: False)',
        )
        parser.add_argument(
            '--base-dir',
            type=str,
            help='기본 디렉토리 경로 (기본값: 프로젝트 루트)',
            default=None
        )
    
    def handle(self, *args, **options):
        logging.basicConfig(level=logging.INFO)
        
        # 파일 경로 결정
        if options['base_dir']:
            base_dir = Path(options['base_dir'])
        else:
            # 프로젝트 루트 디렉토리 (settings.py의 부모의 부모)
            base_dir = Path(settings.BASE_DIR).parent
        
        ies_file_path = base_dir / options['file']
        
        if not exists(ies_file_path):
            self.stdout.write(
                self.style.ERROR(f'IES 파일을 찾을 수 없습니다: {ies_file_path}')
            )
            return
        
        self.stdout.write(f'IES 파일 파싱 시작: {ies_file_path}')
        
        update_mode = options['update']
        count = 0
        count_created = 0
        count_updated = 0
        count_skipped = 0
        
        try:
            with io.open(ies_file_path, 'r', encoding='utf-8') as ies_file:
                ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')
                
                for row in ies_reader:
                    count += 1
                    
                    # 빈 행 스킵
                    if not row.get('ClassID') or row.get('ClassID').strip() == '':
                        continue
                    
                    try:
                        class_id = int(row['ClassID'])
                    except (ValueError, KeyError):
                        self.stdout.write(
                            self.style.WARNING(f'잘못된 ClassID: {row.get("ClassID")}, 행 {count} 건너뜀')
                        )
                        continue
                    
                    # 기존 데이터 확인
                    try:
                        obj = ChallengeModeAutoMap.objects.get(class_id=class_id)
                        exists_flag = True
                    except ChallengeModeAutoMap.DoesNotExist:
                        obj = ChallengeModeAutoMap()
                        exists_flag = False
                    
                    # 업데이트 모드가 아니고 이미 존재하면 스킵
                    if exists_flag and not update_mode:
                        count_skipped += 1
                        continue
                    
                    # 데이터 설정
                    obj.class_id = class_id
                    obj.class_name = row.get('ClassName', '').strip()
                    obj.map_name = row.get('MapName', '').strip()
                    obj.name = row.get('Name', '').strip()
                    obj.value_str = row.get('Value_Str', '').strip() if row.get('Value_Str') else None
                    
                    obj.save()
                    
                    if exists_flag:
                        count_updated += 1
                        if count_updated % 10 == 0:
                            self.stdout.write(f'업데이트 중... ({count_updated}/{count})')
                    else:
                        count_created += 1
                        if count_created % 10 == 0:
                            self.stdout.write(f'생성 중... ({count_created}/{count})')
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'오류 발생: {str(e)}')
            )
            logging.exception('IES 파일 파싱 중 오류 발생')
            return
        
        # 결과 출력
        self.stdout.write(
            self.style.SUCCESS(
                f'\n파싱 완료!\n'
                f'  총 처리: {count}개\n'
                f'  생성: {count_created}개\n'
                f'  업데이트: {count_updated}개\n'
                f'  스킵: {count_skipped}개'
            )
        )
