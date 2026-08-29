# Streamlit チャット UI 設計

作成日: 2026-08-30

## 目的

デモの操作をシェルスクリプト経由から画面に移し、聴衆に見せられる形にします。既存の 5 ステップスクリプトは残し、チャット UI を並列の入口として追加します。

UI で見せるものは 4 つです。

1. ストリーミングされる応答
2. どのツールをどんな引数で呼び、何が返ったか
3. 同一セッションでの会話継続（Memory）
4. 呼び出し時のモデル差し替えと、レイテンシ・トークン数

## 方針

ローカルで起動する Streamlit アプリにします。AWS リソースは一切追加しないため、`teardown.sh` の対象も変わりません。認証は手元の AWS 認証情報をそのまま使います。

ブラウザから直接 `InvokeHarness` を呼ぶ構成は採りません。ブラウザに AWS 認証情報を渡すことになるためです。

## 構成

```
chatui/harness_client.py     AgentCore 呼び出しとイベント正規化（Streamlit 非依存）
chatui/streamlit_app.py      描画のみ
scripts/chat.sh              前提確認 → streamlit run
tests/test_chat_events.py    harness_client の単体テスト
```

ロジックを `harness_client.py` に集約し、`streamlit_app.py` は描画だけにします。Streamlit のスクリプトは実行モデル上そのままでは単体テストしづらいため、テスト対象を非依存モジュール側に置きます。

## 既存コードの変更

`observability/invoke_harness.py` の `parse_stream` は、標準出力へ print しながら最後に集計 dict を返す実装です。逐次配信に使えないため、中身を `iter_stream_events(events)` というジェネレータに切り出し、`parse_stream` をその上に載せ替えます。

不変条件:

- `parse_stream(events, *, emit=True, started_monotonic=None)` のシグネチャを変えない
- 戻り値のキー（`responseText` / `toolUses` / `toolResults` / `usage` / `serviceLatencyMs` / `firstTokenMs` / `stopReason`）を変えない
- `emit=True` のときの標準出力ラベル（`[toolUse]` / `[toolResult]` / `[answer]`）を変えない
- エラーイベント（`internalServerException` / `validationException` / `runtimeClientError`）で `RuntimeError` を投げる挙動を変えない

これにより 5 本のステップスクリプト、`measure_wrong_tool.py`、既存テストは変更なしで通ります。

### `iter_stream_events` が yield するイベント

| type | フィールド |
| --- | --- |
| `text` | `text`（差分） |
| `tool_use` | `name`, `input`（JSON 化に失敗したら生文字列） |
| `tool_result` | `status`, `content` |
| `metadata` | `usage`, `serviceLatencyMs` |
| `stop` | `stopReason` |

`error` はジェネレータからは投げっぱなし（`RuntimeError`）にし、UI 向けの `error` イベントへの変換は `harness_client` 側で行います。CLI の既存挙動を変えないためです。

## `harness_client.stream_turn`

```python
def stream_turn(
    *,
    prompt: str,
    session_id: str,
    model_id: str | None,
    harness_arn: str,
    profile: str,
    region: str,
    actor_id: str,
) -> Iterator[dict]
```

yield するのは次の 5 種類だけです。UI はこの契約だけを知っていればよく、AgentCore のイベント形式には依存しません。

| type | 中身 |
| --- | --- |
| `text` | 応答テキストの差分 |
| `tool_use` | `{name, input}` |
| `tool_result` | `{status, content}` |
| `done` | `{firstTokenMs, elapsedMs, usage}` |
| `error` | `{message}`。これを yield したら打ち切る |

`session_id` が 33 文字未満なら送信前に `ValueError` にします（`runtimeSessionId` の下限）。

CloudWatch へのメトリクス送信と ADOT 計装は UI 経路では行いません。UI はデモの見せ方であり、計測系は既存スクリプトの担当だからです。

## Streamlit 側

状態は 2 つだけ持ちます。

| キー | 中身 |
| --- | --- |
| `session_state.session_id` | ハイフン付き UUID（36 文字） |
| `session_state.messages` | `[{role, blocks}]` |

`blocks` は順序付きのリストで、要素は次のいずれかです。

- `{"kind": "text", "text": str}`
- `{"kind": "tool", "name": str, "input": Any, "status": str | None, "content": Any}`
- `{"kind": "metrics", "firstTokenMs": int, "elapsedMs": int, "usage": dict}`

Streamlit は操作ごとにスクリプトを再実行するため、テキストとツール呼び出しの出現順を履歴で再現するには構造として保持する必要があります。

描画:

- ヘッダにモデルの `selectbox`（`PRIMARY_MODEL_ID` / `ALTERNATE_MODEL_ID`）、session ID の caption、「新しい会話」ボタン
- 「新しい会話」で `session_id` を再生成し `messages` を空にする
- 応答中はイベントを受けながら、`text` はプレースホルダへ追記、`tool_use` は `st.status(name, state="running")` を開いて引数を表示、`tool_result` で同じ status を `complete` にして結果を入れる
- `done` を受けたらレイテンシとトークンを `st.caption` で応答直下に出す
- `error` は `st.error` で表示し、その turn を終了する（アプリは落とさない）

## 起動

```
./scripts/chat.sh
```

`scripts/common.sh` を source して `.demo.env` の検証と承認済みターゲットの確認を通し、`HARNESS_ARN` が無ければ `setup.sh` を促して止めます。そのうえで次を実行します。

```
streamlit run chatui/streamlit_app.py \
  --server.address 127.0.0.1 \
  --server.port 8787 \
  --browser.gatherUsageStats false
```

既定値のままだと全インターフェースに listen し、利用統計も送信されるため、両方を明示的に固定します。

## テスト

`tests/test_chat_events.py`（AWS 呼び出しはモック、Streamlit 非依存）。

- `iter_stream_events` が text / tool_use / tool_result / metadata / stop を正しい順序で yield する
- `tool_use` の分割された入力 JSON が結合されて dict になる
- `stream_turn` がエラーイベントを `error` に変換して打ち切る
- `stream_turn` が `done` に `firstTokenMs` / `elapsedMs` / `usage` を含める
- `session_id` が 33 文字未満なら `ValueError`

既存の `tests/test_stream_parser.py` は変更しません。これが `parse_stream` の後方互換性の担保になります。

## 依存

`requirements.txt` に `streamlit>=1.62,<2` を追加します。`setup.sh` の pip install が伸びますが、AWS リソースは増えません。

## 対象外

- AWS へのデプロイ（Lambda / Function URL / 静的ホスティング）
- 認証・レート制限（`127.0.0.1` バインドで代替）
- 会話履歴の永続化（Memory は Harness 側が持ち、UI は session ID だけを保持）
- UI 経路からの CloudWatch メトリクス送信
