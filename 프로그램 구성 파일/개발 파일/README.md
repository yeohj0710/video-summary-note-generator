# 영상·음성 요약 노트 생성기

릴스, 유튜브 영상, 또는 내 컴퓨터의 영상/음성 파일을 OpenAI API로 전사하고, 읽기 쉬운 전체 스크립트 TXT와 선택 사항인 상세 요약 TXT로 저장하는 Windows 데스크톱 앱입니다.

요약은 기본으로 생성됩니다. 필요 없으면 앱에서 `요약 TXT도 만들기`를 끄면 요약 호출 없이 전사 TXT만 저장합니다.

## 배포 구조

```text
media-summary-note-generator/
  영상·음성 요약 노트 생성기.exe
  사용설명서.html
  README.md
  생성된 노트/
  프로그램 구성 파일/
    openai_api_key_guide.html
    media_source_guide.html
```

## 결과물 구조

작업이 끝나면 `생성된 노트` 폴더 바로 아래에 영상, 전체 스크립트 TXT, 요약 옵션을 켠 경우 요약 TXT가 같은 이름으로 저장됩니다. 영상별 하위 폴더는 만들지 않습니다.

```text
생성된 노트/
  2605091859 영상제목.mp4
  2605091859 영상제목.txt
  2605091859 영상제목_요약.txt
```

파일명은 `YYMMDDHHMM 영상제목` 형식입니다.

## 개발 실행

```powershell
cd "C:\dev\media-summary-note-generator\프로그램 구성 파일\개발 파일"
.\.venv\Scripts\python.exe -m clipnote_ai
```

## 빌드

```powershell
cd "C:\dev\media-summary-note-generator\프로그램 구성 파일\개발 파일"
.\build.ps1
```

빌드가 끝나면 루트의 exe와 `프로그램 구성 파일` 런타임이 갱신됩니다.
