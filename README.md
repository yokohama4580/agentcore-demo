# Amazon Bedrock AgentCore デモ（注文サポートエージェント）

架空の EC 事業者向け注文管理 SaaS のカスタマーサポートエージェントを題材に、
**Amazon Bedrock AgentCore を「AI エージェントを本番運用するための土台」として
一通り触れる**デモです。5 本のスクリプトを順に実行すると、次を実機で確認できます。

| ステップ | 確認できること |
| --- | --- |
| Step 1 | 設定ファイルだけで動くマネージド agent loop（Harness）と、同一セッションでの会話継続（Memory） |
| Step 2 | 既存の REST API を書き換えずに MCP ツールとして使う（Gateway） |
| Step 3 | 「画面上はもっともらしいが、裏で誤ったツールを呼んでいる」失敗をトレースで特定する |
| Step 4 | Harness のバージョンを変えずに、呼び出し時のモデル上書きだけでモデルを差し替える |
| Step 5 | セッション / モデル / ツールの入れ子スパンと、`Builtin.ToolSelectionAccuracy` の採点結果 |

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
./scripts/setup.sh
./scripts/step1-basic.sh
./scripts/step2-tool.sh
./scripts/step3-wrong-tool.sh
./scripts/step4-model-swap.sh
./scripts/step5-traces.sh
./scripts/teardown.sh
```

各スクリプトは引数も対話入力も取りません。

### 誤爆防止（承認済みターゲット）

`.demo.env` の `APPROVED_ACCOUNT_ID` と `APPROVED_REGION` は「ここにだけ作る」という宣言です。
CDK app とすべてのデモスクリプトは、`aws sts get-caller-identity` の実測値がこの宣言と
一致しない限り停止します。誤って別のアカウントへデプロイすることを防ぐための仕組みです。

## アーキテクチャ

```text
デモ用シェルスクリプト
  |
  +-- Python invoke runner
  |     +-- AgentCore Harness（マネージド agent loop / Memory）
  |            +-- Bedrock model
  |            +-- AgentCore Gateway（MCP）
  |                   +-- OpenAPI tool definitions
  |                   +-- Lambda tools API
  |
  +-- ADOT SDK / OTel attributes
         +-- CloudWatch GenAI Observability
         +-- AgentCore Evaluations

API Gateway REST API
  +-- 同じ Lambda tools API
```

`tools-api` は API Gateway と Lambda で構成します。AgentCore Gateway は同じ
OpenAPI 契約と Lambda を IAM 認証で利用するため、エージェント専用に業務ロジックを
書き直しません。

Harness は SigV4 認証、明示的な `maxIterations`、`maxTokens`、`timeoutSeconds` を
設定します。実行ロールの信頼ポリシーには
`bedrock-agentcore.amazonaws.com`、`aws:SourceAccount`、`aws:SourceArn` を設定し、
`iam:PassRole` を含む必要最小限の権限だけを付与します。

## ディレクトリ

```text
tools-api/            Lambda handler、fixture、OpenAPI 3.0、単体テスト
harness/              Harness 設定（表示用のスナップショット）
gateway/              Gateway が公開する tool 一覧（表示用）
observability/        invoke runner、READY 待機、トレース表示、teardown 検証
scripts/
  common.sh           承認済みターゲット確認、見出し、前提チェック
  setup.sh            依存インストール → テスト → CDK deploy → READY 待機
  step1-basic.sh 〜 step5-traces.sh
  measure-wrong-tool.sh  Step 3 の再現率を N 回試行して測る
  teardown.sh         削除と残存 0 件の検証
infra/                TypeScript CDK app とテスト
tests/                ストリーム解析、handler、トレース表示の単体テスト
.demo.env.example     設定テンプレート（実値は git 管理外の .demo.env に置く）
```

## IaC

TypeScript の AWS CDK を使用します。ローカルの CDK CLI が新しい AgentCore リソースより
古い場合があるため、プロジェクト内に現行版を固定しています（`package.json` の
`devDependencies`）。Lambda、API Gateway、IAM、CloudWatch Logs、Harness、Gateway、
GatewayTarget、OnlineEvaluationConfig を CDK 管理下に置きます。

全対応リソースに次のタグを付けます。

```text
Project=agentcore-support-demo
```

ロググループは短い保持期間と `RemovalPolicy.DESTROY` を設定します。サービスが暗黙作成する
リソース（managed Memory、Harness ランタイムのロググループ等）は `teardown.sh` が
サービス固有 API で削除・確認します。

## Harness

`harness/harness.json` はモデル、system prompt、Gateway tool、Memory、実行上限を
まとめた表示用スナップショットです（実際の作成は CDK が行います）。作成後は
`get-harness` をポーリングし、`READY` になってから呼び出します。

呼び出しはデータプレーン `bedrock-agentcore` の `InvokeHarness` を使います。
`runtimeSessionId` はハイフン付き UUID（36 文字）とし、入力は `messages` リストで
渡します。`contentBlockDelta.delta` の `text`、`toolUse`、`toolResult`、
`reasoningContent` と `metadata` を逐次処理します。

## Observability と Evaluations

Harness のネイティブトレースに加え、Python runner を ADOT SDK で計装します。
`session.id`、エージェント入出力、モデル呼び出し、ツール名・引数・結果、各処理時間、
入力・出力トークンを OTel GenAI semantic conventions に沿って記録します。
ADOT Collector は使用しません。

Evaluations は CloudWatch Logs の OTel トレースをデータソースにし、
`Builtin.ToolSelectionAccuracy` と `Builtin.ToolParameterAccuracy` を設定します。

## 各ステップの見どころ

### Step 1: 設定と Memory

```bash
./scripts/step1-basic.sh
```

- 使用中の Harness 設定の要点
- 1 回目のストリーミング応答
- 同じ 36 文字の session ID で 2 回目を呼ぶと、1 回目の会話内容が反映される

### Step 2: 既存 API のツール利用

```bash
./scripts/step2-tool.sh
```

- Gateway が公開する MCP tool 名
- 注文・在庫・配送の 3 系統への問い合わせ
- `toolUse` の tool 名と引数、`toolResult` の要約、最終回答

### Step 3: 誤ツール選択の追跡

```bash
./scripts/step3-wrong-tool.sh
```

`inspect_order_lifecycle` と `lookup_order_shipment_status` はどちらも order/status を
含みます。Step 3 だけ呼び出し時の system prompt override で、注文処理を shipment へ
送る誤った legacy routing rule を注入します（Harness 設定や version は変更しません）。
orders=`PROCESSING`、shipments=`DELIVERED` という fixture の矛盾を使い、画面上は
「処理済み」とだけ返す一見自然な誤答を作ります。

再現率を自分で測る場合は次を実行します（既定 20 回、`WRONG_TOOL_RUNS` で変更可）。

```bash
./scripts/measure-wrong-tool.sh
```

### Step 4: 呼び出し時のモデル差し替え

```bash
./scripts/step4-model-swap.sh
```

同じ質問・同じ上限で、`InvokeHarness` の model override だけを変更します。モデル ID、
応答、first-token / total latency、input / output / total tokens、そして Harness version が
変わっていないことを表示します。

### Step 5: トレースと評価

```bash
./scripts/step5-traces.sh
```

対象セッションの span 階層（agent → model → execute_tool → MCP → model）と、
`Builtin.ToolSelectionAccuracy` の採点結果を表示し、CloudWatch GenAI Observability と
AgentCore Evaluations のコンソール URL を出力します。

Online Evaluation は収集と採点に数分かかるため、直近のライブセッションがまだ未採点の
場合は、同じ条件で採点済みの最新失敗セッションを明示して表示します（ライブ結果と
事前結果を混同しないため）。

## 失敗時の判断

| 症状 | 最初に確認すること |
| --- | --- |
| `CreateHarness` が AccessDenied | 呼び出し元の `iam:PassRole` と実行ロール ARN |
| Harness を呼べない | `get-harness` が `READY` か |
| session ID エラー | ハイフン付き UUID で 33 文字以上か |
| 応答が空 | イベントストリームを反復し `contentBlockDelta` を処理しているか |
| tool が呼ばれない | GatewayTarget が `READY` か、OpenAPI の description が明確か |
| trace が出ない | ADOT SDK、OTel exporter、`session.id`、IAM、log group |
| 評価されない | invoke agent / inference / execute tool span と service name |
| teardown が止まる | Harness → target → Gateway → CDK stack の依存順 |

## Teardown

```bash
./scripts/teardown.sh
```

削除順は Harness / 暗黙 Memory、GatewayTarget、Gateway、CDK stack とし、
CloudFormation 完了後も managed Memory が `ResourceNotFound` になるまでポーリングします。
最後に Resource Groups Tagging API と AgentCore / Lambda / API Gateway /
CloudFormation / S3 のサービス固有一覧を照合し、`Project=agentcore-support-demo` の
残存リソースを表示します。残存が 1 件でもあれば終了コードを非ゼロにし、
「完全削除済み」と報告しません。

Resource Groups Tagging API は削除済みの ARN をしばらく返す場合があるため、
teardown ではサービス固有の Get / List API で実在性を再確認しています。

## 既知の落とし穴

- `runtimeSessionId` は 33 文字以上が必須。ハイフンなしの UUID（32 文字）は弾かれる
- 呼び出しはデータプレーン `bedrock-agentcore` で、`messages` のリストを渡す
- レスポンスはイベントのストリーム。単一の文字列として扱うと出力が落ちる
- `create-harness` の後、`get-harness` が `READY` になるまでポーリングが必要
- `CreateHarness` には `iam:PassRole` が必要
- 従来の Bedrock Agents（classic）とは別物であり、このデモでは使わない
