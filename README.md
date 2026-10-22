# Hermes Research Setup 0.19.0 — Mattermost 내부 한국어 작업보드 · 3+1 프리릴리스

Windows용 연구팀 설치 마법사의 현재 개발 버전입니다. 기존 3+1·전체 페르소나·강제 감사를 유지합니다.
0.19.0은 작업보드·NST 브랜딩 플러그인 자동 설치를 추가한 개발 버전입니다. 새 PC의 전체 설치 검증 완료를 보증하지 않습니다.
기존 설치의 S1·S2·S3 통과 기록은 보존하며, 플러그인 추가 적용은 연구팀 교체나 실모델 검증을 재실행하지 않습니다.

Mattermost 왼쪽 **연구 작업보드**에서 프로젝트·작업 카드·결과 문서·승인 요청과 실제 도구 행동 기록을 봅니다.
Mattermost에는 접수·중요 문제·사용자 확인·최종 결과만 간단히 보고합니다.
기본설정 버튼이 한국어 보드와 NST 브랜딩을 자동 설치합니다. 기존 팀은 **보드·NST만 연결**로 적용할 수 있습니다.
마법사 3단계의 **Mattermost 작업보드 열기** 또는 작업 폴더의 `Mattermost Research Board.url`로도 엽니다.
화면 구성은 제공받은 포크의 흰색·초록색 카드 보드를 기준으로 했습니다.
설치 검증과 실제 연구 프로젝트는 별도 화면이며, 보드를 열었다고 설치 검증이 통과하지 않습니다.
설치·접근 권한·복구 방식은 [Mattermost 플러그인 안내](docs/mattermost-plugins.ko.md)를 확인하세요.

## 실행

연구용 ZIP을 전부 풀고 `Start-HermesResearchSetup.cmd`를 실행합니다.
순서는 **로컬 Mattermost 서버 → Hermes·기존 모델 연결 → 기본설정 자동 구성·실제 설치 검증**입니다.
관리자 계정, 모델 연결과 전송 동의는 사용자가 확인해야 합니다. 네 봇·토큰은 버튼 하나로 발급·재사용합니다.
현재 개발 중인 서버와 같은 포트·프로필을 대상으로 시험하지 마세요.

## 선택한 조합

- 총괄·조사·분석/집필·감사의 3+1, 기존 전체 페르소나 유지.
- 포크의 Git 작업 보드, 독립 역할 실행기, 결과 이벤트에 반응하는 총괄.
- 포크의 Hermes 파일·터미널·공개 웹 도구와 파일 기반 근거 재사용.
- 감사자만 블라인드. 요청 충족·근거·방법·수치·일관성·한계를 검수합니다.
- 중간 감사가 통과한 현재 버전만 후속 작업에 사용하고, 최종 감사 후 첨부를 재다운로드해 검증합니다.
- 기존 Hermes Codex 연결 기본, LiteLLM 라우터 선택 가능.
- 기본 한도: 시도당 2000턴, 작업당 최대 50시도, 일시적 모델 오류 최대 100회, 시도당 180분.
  모든 횟수를 반드시 쓰는 것이 아니며 사용량 상한이 크게 늘어날 수 있습니다.
- 실제 S1·S2·S3 증거가 없으면 설치 완료로 표시하지 않습니다.

[설치 순서](docs/research-guide.ko.md) · [실행 구조와 권한](docs/research-team.md) ·
[이번 수정·검증 범위](docs/verification-0.19.0.md) · [이전 실제 비교](docs/verification-0.17.1.md) ·
[초기 조합 기록](docs/0.17-local-candidate.ko.md)

기존 사용자용 `Start-HermesEasySetup.cmd`와 관리자용 `Start-HermesAdminSetup.cmd`도 유지했습니다.
[관리자 안내](docs/admin-guide.ko.md) · [복구 안내](docs/recovery-guide.ko.md)

## 로컬 검증과 배포

`team/build_manifest.py`로 팀 파일 해시를 갱신한 뒤 PowerShell·Python 모의 테스트를 수행합니다.
`Build-Distributions.ps1 -DestinationRoot <별도 출력 폴더>`는 세 용도의 ZIP과 SHA256SUMS.txt를 만듭니다.
개인 인증·런타임·실험 기록은 패키지에 포함하지 않습니다.
