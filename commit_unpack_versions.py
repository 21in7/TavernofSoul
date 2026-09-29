#!/usr/bin/env python3
"""
각 unpack 폴더를 parser_version.csv의 버전 정보로 커밋하는 스크립트
"""

import os
import subprocess
import csv
import sys
from pathlib import Path

def run_command(cmd, cwd=None):
    """명령어 실행"""
    try:
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {cmd}")
        print(f"Error: {e.stderr}")
        return None

def get_version_info(csv_file):
    """parser_version.csv에서 버전 정보 읽기"""
    versions = {}
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2 and row[0] and row[1]:
                    versions[row[0]] = row[1]
    except FileNotFoundError:
        print(f"Error: {csv_file} 파일을 찾을 수 없습니다.")
        return None
    except Exception as e:
        print(f"Error reading {csv_file}: {e}")
        return None
    
    return versions

def commit_unpack_folder(folder_name, version):
    """특정 unpack 폴더를 지정된 버전으로 커밋"""
    folder_path = f"{folder_name}_unpack"
    
    if not os.path.exists(folder_path):
        print(f"Warning: {folder_path} 폴더가 존재하지 않습니다.")
        return False
    
    print(f"\n=== {folder_name.upper()} 처리 중 ===")
    print(f"폴더: {folder_path}")
    print(f"버전: {version}")
    
    # 해당 폴더로 이동
    os.chdir(folder_path)
    
    # Git 상태 확인
    status = run_command("git status --porcelain")
    if not status:
        print(f"  {folder_name}: 변경사항이 없습니다.")
        os.chdir("..")
        return True
    
    # 모든 변경사항 추가
    add_result = run_command("git add -A")
    if add_result is None:
        print(f"  {folder_name}: git add 실패")
        os.chdir("..")
        return False
    
    # 커밋 메시지 생성
    commit_message = f"Update {folder_name} to version {version}"
    
    # 커밋 실행
    commit_result = run_command(f'git commit -m "{commit_message}"')
    if commit_result is None:
        print(f"  {folder_name}: git commit 실패")
        os.chdir("..")
        return False
    
    print(f"  {folder_name}: 성공적으로 커밋됨")
    
    # 원격 저장소에 푸시 (선택사항)
    push_choice = input(f"  {folder_name}을 원격 저장소에 푸시하시겠습니까? (y/N): ").strip().lower()
    if push_choice in ['y', 'yes']:
        push_result = run_command("git push")
        if push_result is None:
            print(f"  {folder_name}: git push 실패")
        else:
            print(f"  {folder_name}: 원격 저장소에 푸시됨")
    
    # 상위 디렉토리로 돌아가기
    os.chdir("..")
    return True

def main():
    # 스크립트가 있는 디렉토리로 이동
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    print("=== Unpack 폴더 버전 커밋 스크립트 ===")
    
    # parser_version.csv 파일 경로
    csv_file = "parser_tidy/parser_version.csv"
    
    # 버전 정보 읽기
    versions = get_version_info(csv_file)
    if not versions:
        print("버전 정보를 읽을 수 없습니다.")
        sys.exit(1)
    
    print(f"읽은 버전 정보:")
    for name, version in versions.items():
        print(f"  {name}: {version}")
    
    # 처리할 unpack 폴더들
    unpack_folders = ['itos', 'ktos', 'jtos']
    
    print(f"\n처리할 폴더들: {', '.join(unpack_folders)}")
    
    # 사용자 확인
    confirm = input("\n계속 진행하시겠습니까? (y/N): ").strip().lower()
    if confirm not in ['y', 'yes']:
        print("작업이 취소되었습니다.")
        sys.exit(0)
    
    # 각 폴더 처리
    success_count = 0
    for folder in unpack_folders:
        if folder in versions and versions[folder] != '0':
            if commit_unpack_folder(folder, versions[folder]):
                success_count += 1
        else:
            print(f"\n{folder}: 버전 정보가 없거나 0입니다. 건너뜁니다.")
    
    print(f"\n=== 완료 ===")
    print(f"성공: {success_count}/{len(unpack_folders)} 폴더")

if __name__ == "__main__":
    main()
