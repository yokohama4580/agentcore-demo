# Amazon Bedrock AgentCore デモ（注文サポートエージェント）

架空の EC 事業者向け注文管理 SaaS「Asagao」のサポートエージェントを題材に、
**AI エージェントを「作る → 製品に繋ぐ → 精度の壁に当たる → 中身を見る → 仕組みにする」**
という流れを Amazon Bedrock AgentCore で一通り体験するデモです。

| ステップ | 内容 | 操作する画面 |
| --- | --- | --- |
| 1. 作る | エージェント（Harness）を設定だけで作り、その場でテストする | デモ UI の「エージェント設定」／AgentCore コンソール |
| 2. 自社製品に繋ぐ | 同じエージェントを手元のアプリから呼ぶ | デモ UI の「AI アシスタント」 |
| 3. 精度の壁に当たる | モデルを切り替えると、同じ質問への答えが変わる | デモ UI（ヘッダーのモデル切替） |
| 4. 中身を見る | トレースで「なぜ答えが違ったのか」を特定する | CloudWatch GenAI Observability |
| 5. 仕組みにする | Online Evaluations を有効化し、本番トラフィックを継続採点する | AgentCore コンソールの Evaluation |

**Step 1〜5 の操作はブラウザ（デモ UI + AWS コンソール）だけで完結します。**
ターミナルを使うのは事前のデプロイ・練習・後片付けだけです（`setup.sh` / 各 CLI 版
スクリプト / `teardown.sh`）。人前で見せる場では黒い画面を出しません。

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
./scripts/setup.sh   # 土台（tools API / Gateway / IAM ロール）を CDK で構築
./scripts/ui.sh      # デモ UI を起動 → あとは http://127.0.0.1:8788 と AWS コンソールだけ
./scripts/teardown.sh
```

事前練習・実測用の CLI 版（本番のデモでは使いません）:

```bash
./scripts/step1-create-agent.sh   # エージェントを CLI で作る（STEP1_MODE=cli）
./scripts/step3-compare-models.sh # モデル比較を CLI で 1 往復ずつ
./scripts/measure-model-gap.sh    # Step 3 の再現率を N 回試行して測る
./scripts/step4-traces.sh         # スパン階層をターミナルに出す
./scripts/step5-evaluations.sh    # Online Evaluation を CLI で作り採点結果を出す
```

各スクリプトは引数も対話入力も取りません（切り替えは環境変数で行います）。

### 誤爆防止（承認済みターゲット）

`.demo.env` の `APPROVED_ACCOUNT_ID` と `APPROVED_REGION` は「ここにだけ作る」という宣言です。
CDK app とすべてのデモスクリプトは、`aws sts get-caller-identity` の実測値がこの宣言と
一致しない限り停止します。誤って別のアカウントへデプロイすることを防ぐための仕組みです。

## アーキテクチャ

```text
デモ UI（ローカルの React + FastAPI）
  ├── エージェント設定タブ … Step 1: CreateHarness / 状態表示 / その場でテスト
  └── AI アシスタントタブ … Step 2〜3: 顧客に見える画面 + 運用ビュー
AgentCore コンソール（Step 1 の別経路・Step 5: Evaluation の作成）
デモ用シェルスクリプト（事前練習・実測用の CLI 版）
  |
  +-- AgentCore Harness "AsagaoSupportAgent*"（マネージド agent loop / Memory）
         +-- Bedrock model（呼び出し時 override で切替可能）
         +-- AgentCore Gateway（MCP）
                +-- API Gateway REST API + Lambda（既存 API の想定。固定 fixture）

CloudWatch GenAI Observability（Step 4: トレース）
AgentCore Evaluations（Step 5: LLM-as-a-Judge の継続採点）
```

役割分担:

- **CDK スタック（`AgentCoreSupportDemo`）**: 土台だけを管理する。tools API（Lambda +
  API Gateway）、Gateway と GatewayTarget、Harness / Evaluations の実行ロール、ダッシュボード
- **Harness（Step 1）と Online Evaluation（Step 5）**: デモの中で作る。デモ UI でも
  コンソールでも CLI でも作れて、どの経路でも同じ設定になる
  （`harness/harness.json` が単一の定義）

エージェントは**名前の前方一致**（既定は `AsagaoSupportAgent`）で引き当てます。
どの経路で作っても UI が自動的に見つけ、いちばん新しい READY のものを呼びます。
作成に失敗しても直前のエージェントで会話を続けられます。
IAM とロググループの後片付けも同じ前方一致に揃えてあるので、`AsagaoSupportAgentLive`
のような接尾辞付きの名前でも権限と削除の対象に入ります。

## Step 1: 作る

デモ UI の「**エージェント設定**」タブを開き、名前・モデル・指示・ツール・メモリ・
実行上限を確認して「**この設定でエージェントを作成**」を押します。

- Harness はモデル・system prompt・Gateway ツール・Memory・実行上限を**設定として宣言するだけ**。
  コンテナもオーケストレーションコードも書かない
- `CREATING` → `READY` はこの環境の実測で **約 2 分半〜3 分**（画面が自動で追従する）
- READY になったら「**テスト実行**」でその場に 1 往復流せる。
  コンソールの agent sandbox でも同じ質問を試せる
- AWS コンソールのフォームで作る場合は、同じ画面の「AWS コンソールで作る場合」に
  貼り付ける値（実行ロール ARN / モデル ID / Gateway ARN / system prompt / タグ）が
  コピーボタン付きで並んでいる。**名前は `AsagaoSupportAgent` で始めること**、
  **タグ `Project=agentcore-support-demo` を必ず付けること**（teardown が削除対象を
  特定する鍵）
- 表示される ARN は AWS アカウント ID を隠してある（コピーされる値は実物のまま）

CLI で作る場合は `STEP1_MODE=cli ./scripts/step1-create-agent.sh`（事前練習用）。

## Step 2: 自社製品に繋ぐ

デモ UI の「**AI アシスタント**」タブに切り替えます（Step 1 の画面からは
「自社製品の画面へ →」でも移動できます）。UI の起動は事前に済ませておきます。

```bash
./scripts/ui.sh   # 事前準備。以降ターミナルには戻らない
```

`http://127.0.0.1:8788` を開きます。AWS リソースは追加しません（ローカルの FastAPI が
`InvokeHarness` のイベントストリームを SSE に変換してブラウザへ中継するだけ）。

- **左ペイン（顧客に見える画面）**: Asagao の AI アシスタント。ストリーミング応答・定型質問チップ・自由入力
- **右ペイン（運用ビュー）**: 同じターンの裏側。モデル・ツール呼び出しの引数と結果・
  所要時間・first-token / total レイテンシ・in/out トークン・ターン比較テーブル。
  「裏側を隠す」で閉じられる
- **ヘッダー**: 画面の切り替え（エージェント設定 / AI アシスタント）、モデルの切り替え
  （呼び出し時 override。Harness version は変わらない）、session ID 表示、「新しい会話」
- 同じ session ID のまま続けて質問すると会話が継続する（Memory）。「新しい会話」を押すと
  session ID が変わるが、**画面のターンは消えず**、会話の区切り線が入る（Step 3 のモデル比較を
  会話をまたいで見せるため）
- 運用ビューの下端に **session ID のコピーボタン**と CloudWatch / Evaluations への
  リンクがある（Step 4 でセッションを探すときに使う）

フロントエンドを変更したら `UI_REBUILD=1 ./scripts/ui.sh` で再ビルドできます。

## Step 3: 精度の壁に当たる

デモ UI でチップ「**注文 A-100 の商品は、いま在庫がありますか？**」を送り、
**「新しい会話」を押してから**モデルを切り替えて同じチップをもう一度送ります
（CLI 版は `./scripts/step3-compare-models.sh`）。会話を分ける理由は下記のとおりです。

この質問への正しい対応は「注文照会で SKU を特定 → 在庫照会」の **2 段のツール呼び出し**ですが、
注文照会ツール（`inspect_order_lifecycle`）の説明文には「注文の明細（SKU）も返す」ことが
書かれていません。既存 API をそのまま Gateway に登録したときに起こりがちな、説明文の情報不足です。

- **Claude Haiku 4.5**: ツールの説明文を読んで「SKU が分からないので在庫を確認できない」と
  回答し、タスクを完遂しない
- **Nova 2 Lite**: とりあえず注文照会を呼び、返ってきた明細から SKU を見つけて在庫まで辿り着く

同じエージェント・同じ質問なのに、モデルを切り替えると答えが変わります。しかも
**どちらが正しいかは画面からは判定できません**。これが Step 4 への入口です。

**会話は分けます。**同じ会話の中でモデルだけ切り替えると、直前のターンの「SKU が分からない」
という回答が会話履歴に残り、次のモデルもそれを引き継いで同じ結論を返すことがあります
（この環境で実測）。「新しい会話」を押すと session ID が変わり、モデルの違いだけを比べられます。
顧客に見える画面と運用ビューはどちらも会話をまたいでターンを表示し続けるので、
2 つの答えは並んだまま残ります（ターン比較表には「会話」列が出ます）。

再現性のため、呼び出し時の model override は `temperature: 0.0` を指定しています。
この環境の実測（temperature 0.0・新規セッション各 8 回）では、Haiku 4.5 は 8 回全てで
タスク未完遂、Nova 2 Lite は 8 回全てで完遂でした（system prompt を日本語にした後の
各 4 回でも 0/4 と 4/4 で同じ向きでした）。再現率を自分で測る場合
（既定 各10回、`MODEL_GAP_RUNS` で変更可）:

```bash
./scripts/measure-model-gap.sh
```

## Step 4: 中身を見る

運用ビューの「GenAI Observability ↗」から CloudWatch を開き、Bedrock AgentCore の
Sessions / Traces で Step 3 の 2 セッションを見比べます（セッションは運用ビューの
コピーボタンで取った session ID で特定できます）。スパン階層は
agent → model → execute_tool → MCP → model の入れ子で、片方にはツール呼び出しの
スパンが 2 つ連なり、もう片方には 1 つもありません。
「なぜ答えが違ったのか」がモデルの中身を覗かなくてもトレースから特定でき、根本原因が
**モデルの優劣ではなくツール説明文の品質**にあると分かります。

同じ内容をターミナルで確認する CLI 版（事前練習用）:

```bash
./scripts/step4-traces.sh
```

## Step 5: 仕組みにする

AgentCore コンソールの **Evaluation → Create evaluation configuration** で、
評価器（`GoalSuccessRate` / `Helpfulness` / `ToolSelectionAccuracy` /
`ToolParameterAccuracy`）・データソース（Step 1 で作ったエージェントのエンドポイント、
またはそのロググループ + サービス名）・サンプリング 100% ・実行ロール
（スタック出力の `EvaluationRoleArn`）を指定して作成します。

- **名前は `AsagaoSupportAgentEvaluation` で始めること**。実行ロールは結果用ロググループ
  `/aws/bedrock-agentcore/evaluations/results/AsagaoSupportAgentEvaluation*` にだけ
  書き込めるので、別の名前だと作成が `ValidationException` で落ちる
- 採点は継続スケジュールで走るため反映まで時間がかかる（この環境の実測では速いときで
  10 分弱、遅いときは 1 時間近く）。人前では**事前に採点済みのものを開く**

CLI 版（事前練習用。作成 + 採点結果の表示）:

```bash
./scripts/step5-evaluations.sh
```

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
| UI が「エージェントがまだありません」 | 名前が `AsagaoSupportAgent` で始まっているか（前方一致で探している） |
| Memory の `ListEvents` が AccessDenied | 実行ロールの `memory/AsagaoSupportAgent*` の範囲に収まる名前か |
| Evaluation 作成が `ValidationException` | 名前が `AsagaoSupportAgentEvaluation` で始まっているか |

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
harness/harness.json  Harness の定義（Step 1 の UI / コンソール / CLI 共通の単一ソース）
gateway/              Gateway が公開する tool 一覧（表示用）
observability/        invoke runner、Step 1〜5 の実装、teardown 検証
scripts/
  common.sh           承認済みターゲット確認、見出し、前提チェック
  setup.sh            依存インストール → テスト → CDK deploy（土台のみ）
  step1-create-agent.sh  Harness の作成（事前練習用。console 伴走 / STEP1_MODE=cli）
  ui.sh               デモ UI（Step 1〜3 をブラウザで操作。ローカルのみ）
  step3-compare-models.sh / step4-traces.sh / step5-evaluations.sh
  measure-model-gap.sh   Step 3 の再現率を N 回試行して測る
  teardown.sh         削除と残存 0 件の検証
frontend/             デモ UI のフロントエンド（Vite + React。ビルド成果物は dist/）
server/               デモ UI のバックエンド（FastAPI。InvokeHarness を SSE に変換）
chatui/               Harness のストリーミングクライアント + エージェント作成/検出（server が利用）
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

Harness と Online Evaluation はデモの筋書き上、CDK ではなく画面（デモ UI / コンソール）
または CLI で作ります（Step 1 / Step 5）。teardown はこの 2 つをサービス API で
名前の前方一致で削除してから `cdk destroy` を実行します。

## 既知の落とし穴

- `runtimeSessionId` は 33 文字以上が必須。ハイフンなしの UUID（32 文字）は弾かれる
- 呼び出しはデータプレーン `bedrock-agentcore` で、`messages` のリストを渡す
- レスポンスはイベントのストリーム。単一の文字列として扱うと出力が落ちる
- `create-harness` の後、`get-harness` が `READY` になるまでポーリングが必要
- `CreateHarness` には `iam:PassRole` が必要
- コンソールで Harness を作る場合、タグを付け忘れると teardown の削除対象から漏れる
- 実行ロールの Memory 権限は `memory/<エージェント名の前方一致>*` にしておく。
  `AsagaoSupportAgent-*` のようにハイフンで止めると、`AsagaoSupportAgentLive` の
  managed Memory（`memory/AsagaoSupportAgentLive-xxxx`）に一致せず `ListEvents` で落ちる
- 同じ理由で、Evaluation の結果用ロググループの権限もハイフンで止めない。
  止めると `CreateOnlineEvaluationConfig` が「execution role does not have permissions
  to create log group」で失敗する
- 同じ名前のエージェントを削除直後に作り直すと、managed Memory の削除が終わるまで
  `CREATE_FAILED`（`Memory with name ... already exists`）になる。数分待ってから作り直す
- `harness/harness.json` を変えたら**ブラウザのタブを再読み込みする**。デモ UI の作成フォームは
  ページ読み込み時の設定を保持するため、古いタブから作ると古い設定のエージェントができる
- 従来の Bedrock Agents（classic）とは別物であり、このデモでは使わない
