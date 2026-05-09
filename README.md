# ClipNote AI

릴스, 유튜브 영상, 또는 내 컴퓨터의 동영상 파일을 넣으면 OpenAI API로 음성을 전사하고, 문장을 다듬은 뒤 주요 장면 이미지와 함께 한국어 노트를 만들어 주는 Windows 데스크톱 앱입니다.

## 지금 되는 것

- YouTube / 공개 Reels 링크 다운로드
- 로컬 동영상 파일 선택
- OpenAI 전사 API로 음성 전사
- 맞춤법, 띄어쓰기, 문장부호, 문맥상 어색한 부분 정리
- 영상 길이와 내용 밀도를 기준으로 주요 장면 수 자동 결정
- 주요 장면 시점의 화면 캡처
- `summary.md`, `summary.html`, `transcript.txt`, `metadata.json`, `frames/` 출력
- OpenAI API 키 입력 및 선택 저장

## 출력 구조

작업이 끝나면 선택한 출력 폴더 아래에 이런 폴더가 생깁니다.

```text
outputs/
  20260509_132000_영상제목/
    summary.md
    summary.html
    transcript.txt
    metadata.json
    frames/
      scene_01_00-00-12.jpg
      scene_02_00-00-28.jpg
```

Notion에는 `summary.md`를 가져오거나, `summary.html`을 브라우저로 열어 필요한 부분을 복사해서 붙여 넣으면 됩니다.

## 배포 파일

빌드 후 배포용 폴더는 다음처럼 구성됩니다.

```text
release/
  ClipNoteAI/
    ClipNoteAI.exe
    사용설명서.html
    outputs/
  ClipNoteAI.zip
```

사용자는 `사용설명서.html`을 먼저 열어 사용법을 확인한 뒤 `ClipNoteAI.exe`를 실행하면 됩니다. 결과물은 기본적으로 같은 폴더의 `outputs`에 저장됩니다.

## 개발 실행

```powershell
cd C:\dev\clipnote-ai
.\run_app.ps1
```

## exe 빌드

```powershell
cd C:\dev\clipnote-ai
.\build.ps1
```

빌드 스크립트는 가상환경 생성, 의존성 설치, 테스트 실행, PyInstaller 패키징, zip 생성까지 처리합니다.

## GitHub 배포

이 repo에는 `.github/workflows/windows-build.yml`이 포함되어 있습니다. GitHub에 push한 뒤 Actions 탭에서 `Windows Build`를 수동 실행하면 `ClipNoteAI.zip` 아티팩트를 받을 수 있습니다.

태그를 만들어 push해도 빌드가 실행됩니다.

```powershell
git tag v0.1.0
git push origin v0.1.0
```

## OpenAI 모델

전사 기본값은 `gpt-4o-mini-transcribe`입니다. OpenAI 공식 문서 기준으로 전사 API는 `gpt-4o-mini-transcribe`, `gpt-4o-transcribe`, `gpt-4o-transcribe-diarize` 계열을 제공합니다.

문장 정리와 주요 장면 선택은 기본적으로 `gpt-4.1-mini`를 사용합니다. 계정에서 다른 모델을 쓰고 싶다면 앱 화면에서 `gpt-5.4-mini`, `gpt-4o-mini` 등으로 바꿀 수 있습니다.

## Reels 다운로드 참고

Instagram Reels는 공개 링크만 안정적으로 동작합니다. 로그인이나 연령 확인이 필요한 링크는 앱에서 `브라우저 쿠키 사용`을 켠 뒤 Chrome 또는 Edge를 선택해 시도할 수 있습니다.

## API 키 저장

`이 PC에 API 키 저장`을 체크하면 `%APPDATA%\ClipNoteAI\settings.json`에 저장됩니다. 공용 PC에서는 체크하지 않는 것을 권장합니다.

## 제한 사항

- 영상에 오디오 트랙이 있어야 합니다.
- 매우 긴 영상은 전사 비용과 시간이 커질 수 있습니다.
- Reels/YouTube 다운로드는 사이트 정책, 로그인 상태, 지역 제한에 따라 실패할 수 있습니다.
- Notion API 직접 업로드는 아직 넣지 않았습니다. 현재는 Markdown/HTML 기반으로 Notion에 가져오는 흐름입니다.
