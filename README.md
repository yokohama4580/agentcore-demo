# Amazon Bedrock AgentCore デモ（注文サポートエージェント）

架空の EC 事業者向け注文管理 SaaS「Asagao」のサポートエージェントを題材に、
**AI エージェントを「作る → 製品に繋ぐ → 精度の壁に当たる → 中身を見る → 仕組みにする」**
という流れを Amazon Bedrock AgentCore で一通り体験するデモです。

| ステップ | 内容 | 使うもの |
| --- | --- | --- |
| 1. 作る | コンソール（または CLI）で Harness を作成し、その場でテストする | AgentCore コンソール / `step1-create-agent.sh` |
| 2. 自社製品に繋ぐ | 手元のアプリ（2 ペインのデモ UI）から同じエージェントを呼ぶ | `ui.sh` |
| 3. 精度の壁に当たる | モデルを切り替えると、同じ質問への答えが変わる | デモ UI / `step3-compare-models.sh` |
| 4. 中身を見る | トレースで「なぜ答えが違ったのか」を特定する | `step4-traces.sh` / CloudWatch GenAI Observability |
| 5. 仕組みにする | Online Evaluations を有効化し、本番トラフィックを継続採点する | `step5-evaluations.sh` / AgentCore Evaluations |

デモ用のデータは固定 fixture のみで、DB も VPC も使いません。`./scripts/teardown.sh`
一発で全リソースを削除し、残存 0 件を検証します。

## 前提

| 項目 | 内容 |
| --- | --- |
| AWS アカウント | **検証用 / サンドボックスのアカウント**。本番アカウントでは実行しないこと |
| 権限 | CDK deploy 相当（Lambda / API Gateway / IAM / CloudWatch / Bedrock AgentCore の作成） |
| リージョン | AgentCore の Harness / Gateway / Observability / Evaluations が使えるリージョン。既定は `ap-northeast-1`（東京） |
| ツール | AWS CLI v2、Node.js 20 以上、Python 3.12 以上 |
| Bedrock | 使用する 2 モデルにアクセスできること（既定は Claude Haiku 4.5 と Nova 2 Lite の東京クロスリージョン推論プロファイル） |
| コスト | Lambda / API Gateway / CloudWatch Logs / Bedrock のトークン課金。数十回の呼び出しなら小額だが、**使い終わったら必ず teardown する** |

Harness と Evaluations のリージョン対応は AWS 公式の
[Supported AWS Regions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html)
と
[AgentCore endpoints and quotas](https://docs.aws.amazon.com/general/latest/gr/bedrock_agentcore.html)
で確認してください。Evaluations はアジア太平洋内のクロスリージョン推論を利用する場合があります。

## クイックスタート

```bash
git clone https://github.com/yokohama4580/agentcore-demo.git
cd agentcore-demo
cp .demo.env.example .demo.env
# .demo.env の AWS_PROFILE / APPROVED_ACCOUNT_ID / APPROVED_REGION を自分の値に書き換える
./scripts/setup.sh                # 土台（tools API / Gateway / IAM ロール）を CDK で構築
./scripts/step1-create-agent.sh   # エージェント本体を作る（既定はコンソール作成の伴走）
./scripts/ui.sh                   # デモ UI（Step 2〜3 はブラウザで操作）
./scripts/step3-compare-models.sh # Step 3 の CLI 版
./scripts/step4-traces.sh
./scripts/step5-evaluations.sh
./scripts/teardown.sh
```

各スクリプトは引数も対話入力も取りません（切り替えは環境変数で行います）。

### 誤爆防止（承認済みターゲット）

`.demo.env` の `APPROVED_ACCOUNT_ID` と `APPROVED_REGION` は「ここにだけ作る」という宣言です。
CDK app とすべてのデモスクリプトは、`aws sts get-caller-identity` の実測値がこの宣言と
一致しない限り停止します。誤って別のアカウントへデプロイすることを防ぐための仕組みです。

## アーキテクチャ

```text
AgentCore コンソール（Step 1: 作成・sandbox テスト）
デモ UI（Step 2〜3: ローカルの React + FastAPI）
デモ用シェルスクリプト（CLI 版）
  |
  +-- AgentCore Harness "AsagaoSupportAgent"（マネージド agent loop / Memory）
         +-- Bedrock model（呼び出し時 override で切替可能）
         +-- AgentCore Gateway（MCP）
                +-- API Gateway REST API + Lambda（既存 API の想定。固定 fixture）

CloudWatch GenAI Observability（Step 4: トレース）
AgentCore Evaluations（Step 5: LLM-as-a-Judge の継続採点）
```

役割分担:

- **CDK スタック（`AgentCoreSupportDemo`）**: 土台だけを管理する。tools API（Lambda +
  API Gateway）、Gateway と GatewayTarget、Harness / Evaluations の実行ロール、ダッシュボード
- **Harness（Step 1）と Online Evaluation（Step 5）**: デモの中で作る。コンソールでも
  CLI でも作れて、どちらの経路でも同じ設定になる（`harness/harness.json` が単一の定義）

## Step 1: 作る

```bash
./scripts/step1-create-agent.sh              # コンソール作成の伴走（貼り付け値を表示して READY まで待つ）
STEP1_MODE=cli ./scripts/step1-create-agent.sh  # CreateHarness API で直接作成
```

- Harness はモデル・system prompt・Gateway ツール・Memory・実行上限を**設定として宣言するだけ**。
  コンテナもオーケストレーションコードも書かない
- コンソールで作る場合もタグ `Project=agentcore-support-demo` を必ず付ける
  （teardown が削除対象を特定する鍵）
- READY 後にテスト質問を 1 回流す。コンソールの agent sandbox でも同じ質問を試せる

## Step 2: 自社製品に繋ぐ

```bash
./scripts/ui.sh
```

`http://127.0.0.1:8788` を開きます。AWS リソースは追加しません（ローカルの FastAPI が
`InvokeHarness` のイベントストリームを SSE に変換してブラウザへ中継するだけ）。

- **左ペイン（顧客に見える画面）**: Asagao の AI アシスタント。ストリーミング応答・定型質問チップ・自由入力
- **右ペイン（運用ビュー）**: 同じターンの裏側。モデル・ツール呼び出しの引数と結果・
  所要時間・first-token / total レイテンシ・in/out トークン・ターン比較テーブル。
  「裏側を隠す」で閉じられる
- **ヘッダー**: モデルの切り替え（呼び出し時 override。Harness version は変わらない）、
  session ID 表示、「新しい会話」
- 同じ session ID のまま続けて質問すると会話が継続する（Memory）

フロントエンドを変更したら `UI_REBUILD=1 ./scripts/ui.sh` で再ビルドできます。

## Step 3: 精度の壁に当たる

デモ UI でチップ「**注文 A-100 の商品は、いま在庫がありますか？**」を、モデルを切り替えて
2 回送ります（CLI 版は `./scripts/step3-compare-models.sh`）。

この質問への正しい対応は「注文照会で SKU を特定 → 在庫照会」の **2 段のツール呼び出し**ですが、
注文照会ツール（`inspect_order_lifecycle`）の説明文には「注文の明細（SKU）も返す」ことが
書かれていません。既存 API をそのまま Gateway に登録したときに起こりがちな、説明文の情報不足です。

- **Claude Haiku 4.5**: ツールの説明文を読んで「SKU が分からないので在庫を確認できない」と
  回答し、タスクを完遂しない
- **Nova 2 Lite**: とりあえず注文照会を呼び、返ってきた明細から SKU を見つけて在庫まで辿り着く

同じエージェント・同じ質問なのに、モデルを切り替えると答えが変わります。しかも
**どちらが正しいかは画面からは判定できません**。これが Step 4 への入口です。

再現性のため、呼び出し時の model override は `temperature: 0.0` を指定しています。
この環境の実測（temperature 0.0・新規セッション各 8 回）では、Haiku 4.5 は 8 回全てで
タスク未完遂、Nova 2 Lite は 8 回全てで完遂でした。再現率を自分で測る場合
（既定 各10回、`MODEL_GAP_RUNS` で変更可）:

```bash
./scripts/measure-model-gap.sh
```

## Step 4: 中身を見る

```bash
./scripts/step4-traces.sh
```

Step 3 の 2 セッションのスパン階層（agent → model → execute_tool → MCP → model）を並べます。
片方にはツール呼び出しのスパンが 2 つ連なり、もう片方には 1 つもありません。
「なぜ答えが違ったのか」がモデルの中身を覗かなくてもトレースから特定でき、根本原因が
**モデルの優劣ではなくツール説明文の品質**にあると分かります。
CloudWatch GenAI Observability のコンソール URL も出力します。

## Step 5: 仕組みにする

```bash
./scripts/step5-evaluations.sh
```

Online Evaluation（`GoalSuccessRate` / `Helpfulness` / `ToolSelectionAccuracy` /
`ToolParameterAccuracy`、サンプリング 100%）を作成し、直近セッションの採点結果を表示します。
採点は継続スケジュールで走るため反映まで数分かかります（この環境の実測では 8 分超）。

Step 4 の「人がトレースを見て気付く」を、「本番トラフィックを LLM-as-a-Judge が
継続採点して落ちたら気付ける」に置き換えるのがこのステップです。改善（ツール説明文の修正）は
Gateway target の `toolOverrides` の description を直して `cdk deploy` するだけで、
エージェント側のコードはありません。

## 失敗時の判断

| 症状 | 最初に確認すること |
| --- | --- |
| `CreateHarness` が AccessDenied | 呼び出し元の `iam:PassRole` と実行ロール ARN |
| Harness を呼べない | `get-harness` が `READY` か |
| session ID エラー | ハイフン付き UUID で 33 文字以上か |
| 応答が空 | イベントストリームを反復し `contentBlockDelta` を処理しているか |
| tool が呼ばれない | GatewayTarget が `READY` か、OpenAPI の description が明確か |
| trace が出ない | Transaction Search の有効化、`session.id`、IAM、log group |
| 評価されない | invoke agent / inference / execute tool span と service name |
| teardown が止まる | Harness → Evaluation → CDK stack の依存順 |

## Teardown

```bash
./scripts/teardown.sh
```

削除順は Online Evaluation、Harness（暗黙の managed Memory 含む）、CDK stack とし、
CloudFormation 完了後も managed Memory が `ResourceNotFound` になるまでポーリングします。
最後に Resource Groups Tagging API と AgentCore / Lambda / API Gateway /
CloudFormation / S3 のサービス固有一覧を照合し、`Project=agentcore-support-demo` の
残存リソースを表示します。残存が 1 件でもあれば終了コードを非ゼロにし、
「完全削除済み」と報告しません。

Resource Groups Tagging API は削除済みの ARN をしばらく返す場合があるため、
teardown ではサービス固有の Get / List API で実在性を再確認しています。

## ディレクトリ

```text
tools-api/            Lambda handler、fixture、OpenAPI 3.0、単体テスト
harness/harness.json  Harness の定義（Step 1 のコンソール / CLI 両経路の単一ソース）
gateway/              Gateway が公開する tool 一覧（表示用）
observability/        invoke runner、Step 1〜5 の実装、teardown 検証
scripts/
  common.sh           承認済みターゲット確認、見出し、前提チェック
  setup.sh            依存インストール → テスト → CDK deploy（土台のみ）
  step1-create-agent.sh  Harness の作成（console 伴走 / STEP1_MODE=cli）
  ui.sh               Step 2〜3 のデモ UI（ローカルのみ）
  step3-compare-models.sh / step4-traces.sh / step5-evaluations.sh
  measure-model-gap.sh   Step 3 の再現率を N 回試行して測る
  teardown.sh         削除と残存 0 件の検証
frontend/             デモ UI のフロントエンド（Vite + React。ビルド成果物は dist/）
server/               デモ UI のバックエンド（FastAPI。InvokeHarness を SSE に変換）
chatui/               Harness のストリーミングクライアント（server が利用）
infra/                TypeScript CDK app とテスト
tests/                ストリーム解析、handler、サーバー、採点表示の単体テスト
.demo.env.example     設定テンプレート（実値は git 管理外の .demo.env に置く）
```

## IaC

TypeScript の AWS CDK を使用します。ローカルの CDK CLI が新しい AgentCore リソースより
古い場合があるため、プロジェクト内に現行版を固定しています（`package.json` の
`devDependencies`）。Lambda、API Gateway、IAM、CloudWatch Logs、Gateway、
GatewayTarget を CDK 管理下に置き、全対応リソースに `Project=agentcore-support-demo`
タグを付けます。

Harness と Online Evaluation はデモの筋書き上、CDK ではなくコンソール / CLI で作ります
（Step 1 / Step 5）。teardown はこの 2 つをサービス API で削除してから
`cdk destroy` を実行します。

## 既知の落とし穴

- `runtimeSessionId` は 33 文字以上が必須。ハイフンなしの UUID（32 文字）は弾かれる
- 呼び出しはデータプレーン `bedrock-agentcore` で、`messages` のリストを渡す
- レスポンスはイベントのストリーム。単一の文字列として扱うと出力が落ちる
- `create-harness` の後、`get-harness` が `READY` になるまでポーリングが必要
- `CreateHarness` には `iam:PassRole` が必要
- コンソールで Harness を作る場合、タグを付け忘れると teardown の削除対象から漏れる
- 従来の Bedrock Agents（classic）とは別物であり、このデモでは使わない
