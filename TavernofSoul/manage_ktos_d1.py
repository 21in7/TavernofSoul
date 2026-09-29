#!/usr/bin/env python
"""Django's command-line utility for administrative tasks with Cloudflare D1 database."""
import os
import sys


def main():
    """Run administrative tasks with D1 database settings."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'TavernofSoul.settings_ktos_d1')
    
    # D1 데이터베이스 환경 변수 설정
    if not os.getenv('CLOUDFLARE_D1_DATABASE_URL'):
        # 로컬 개발용 D1 데이터베이스 경로 설정
        os.environ['CLOUDFLARE_D1_DATABASE_URL'] = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            'TavernofSoul', 
            'db_ktos_d1.sqlite3'
        )
    
    # D1 쓰기 전용 모드 환경 변수
    os.environ['DATABASE_WRITE_ONLY'] = 'True'
    os.environ['AUTO_CREATE_TABLES'] = 'True'
    os.environ['AUTO_MIGRATE'] = 'True'
    
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    
    # D1 데이터베이스 초기화 명령어 자동 실행
    if len(sys.argv) == 1 or (len(sys.argv) == 2 and sys.argv[1] == 'runserver'):
        print("🔧 D1 데이터베이스 초기화 중...")
        
        # 마이그레이션 실행
        try:
            from django.core.management import execute_from_command_line
            execute_from_command_line(['manage_ktos_d1.py', 'migrate', '--run-syncdb'])
            print("✅ D1 데이터베이스 마이그레이션 완료")
        except Exception as e:
            print(f"⚠️  마이그레이션 실행 중 오류: {e}")
    
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
