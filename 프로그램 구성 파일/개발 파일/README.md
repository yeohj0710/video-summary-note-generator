# 동영상 요약 노트 생성기

developed by yeohj0710

릴스, 유튜브 영상, 또는 내 컴퓨터의 동영상 파일을 넣으면 OpenAI API로 음성을 전사하고, 문장을 다듬은 뒤 주요 화면과 함께 PDF/HTML/Markdown 노트를 만들어 주는 Windows 데스크톱 앱입니다.

## 사용자가 보는 폴더 구조

GitHub에서 이 저장소를 ZIP으로 내려받아 압축을 풀면 루트에는 사용자가 만질 것만 보이도록 정리합니다.

```text
video-summary-note-generator/
  동영상 요약 노트 생성기.exe
  사용설명서.html
  생성된 노트/
  프로그램 구성 파일/
```

- `동영상 요약 노트 생성기.exe`: 프로그램 실행 파일입니다.
- `사용설명서.html`: 일반 사용자용 상세 사용 설명서입니다.
- `생성된 노트`: 프로그램이 만든 PDF, HTML, Markdown, 자막 파일이 저장되는 폴더입니다.
- `프로그램 구성 파일`: 실행에 필요한 라이브러리와 개발 파일이 들어 있는 폴더입니다. 삭제하거나 이름을 바꾸면 실행이 안 될 수 있습니다.

## 주요 기능

- YouTube / 공개 Reels 링크 다운로드
- 로컬 동영상 파일 선택
- 링크 방식과 파일 방식을 분리한 입력 화면
- OpenAI 전사 API로 음성 전사
- 맞춤법, 띄어쓰기, 문장부호, 문맥상 어색한 부분 정리
- 영상 길이와 내용에 맞춘 주요 화면 개수 자동 결정
- 주요 화면 시점의 이미지 캡처
- `summary.pdf`, `summary.html`, `summary.md`, `transcript.txt`, `metadata.json`, `frames/` 출력
- OpenAI API 키 입력 및 선택 저장

## 결과물 구조

작업이 끝나면 `생성된 노트` 폴더 안에 영상별 새 폴더가 생깁니다.

```text
생성된 노트/
  20260509_132000_영상제목/
    summary.pdf
    summary.html
    summary.md
    transcript.txt
    metadata.json
    frames/
      scene_01_00-00-12.jpg
      scene_02_00-00-28.jpg
```

다른 사람에게 전달할 때는 `summary.pdf`가 가장 편합니다. Notion에 정리하고 싶으면 `summary.md`를 가져오거나, `summary.html`을 브라우저로 열어 필요한 부분을 복사해 붙여 넣으면 됩니다.

## 개발 실행

개발용 파일은 루트가 아니라 `프로그램 구성 파일\개발 파일` 안에 있습니다.

```powershell
cd "C:\dev\video-summary-note-generator\프로그램 구성 파일\개발 파일"
.\run_app.ps1
```

## exe 빌드

```powershell
cd "C:\dev\video-summary-note-generator\프로그램 구성 파일\개발 파일"
.\build.ps1
```

빌드 스크립트는 가상환경 생성, 의존성 설치, 테스트 실행, PyInstaller 빌드, 루트 폴더 정리를 처리합니다. 빌드가 끝나면 사용자가 보는 구조는 다음처럼 유지됩니다.

```text
video-summary-note-generator/
  동영상 요약 노트 생성기.exe
  사용설명서.html
  생성된 노트/
  프로그램 구성 파일/
    개발 파일/
    ...실행에 필요한 구성 파일들
```

## GitHub 배포 방식

설치 파일 없이 저장소 자체를 배포합니다. 사용자는 GitHub에서 `Code` -> `Download ZIP`으로 저장소를 내려받고, 압축을 푼 뒤 `동영상 요약 노트 생성기.exe`를 실행하면 됩니다.

## OpenAI 모델

전사 기본값은 `gpt-4o-mini-transcribe`입니다. 문장 정리와 주요 화면 선택은 비용 효율을 위해 기본적으로 `gpt-5-nano`를 사용합니다. 더 좋은 품질이 필요하면 프로그램 화면에서 `gpt-5.4-mini` 같은 상위 모델로 바꿀 수 있습니다.

## Reels 다운로드 참고

Instagram Reels는 공개 링크일 때 가장 안정적으로 동작합니다. 로그인이 필요하거나 연령 확인이 필요한 링크는 `브라우저 쿠키 사용`을 켜고 Chrome 또는 Edge를 선택해 시도할 수 있습니다.

## API 키 저장

`이 PC에 API 키 저장`을 체크하면 `%APPDATA%\VideoSummaryNoteGenerator\settings.json`에 저장됩니다. 공용 PC에서는 체크하지 않는 것을 권장합니다.

## 제한 사항

- 영상에 오디오 트랙이 있어야 합니다.
- 매우 긴 영상은 전사 비용과 처리 시간이 커질 수 있습니다.
- Reels/YouTube 다운로드는 사이트 정책, 로그인 상태, 지역 제한에 따라 실패할 수 있습니다.
- Notion API 직접 업로드는 아직 넣지 않았습니다. 현재는 PDF/Markdown/HTML을 만들어 Notion에 가져오는 방식입니다.

