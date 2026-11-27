# 清禾合唱排练提示灯

清禾社区合唱团用这套本地服务编排、展示和核对当天的排练提示。老师从节目谱选择乐段，值班员按固定校样发卡，甲乙两台记录声部实际看到的提示，领队按结册核对。灯台的已提交实亮流水是本工程的实际点亮记录。

## 核验与演示

在项目根目录使用 Python 3.11。工程只依赖标准库和 Python 自带的 SQLite 支持。

```sh
python3 -B check_project.py
python3 -B demo.py
python3 -B pause_fixture.py
```

标准回归入口由项目控制台提供。直接运行完整测试套件也可使用 `python3 -B -m unittest discover -v`。测试和演示启用独立临时目录、实际 SQLite 数据库和环回 HTTP 服务。样例位于 `sample.json`，演示经接口显式导入，检查卡项顺序、失答时的待查、原灯次复领和结册复读。`pause_fixture.py` 按 `PAUSE_BOOK.md` 的约定演示暂停取点：交错发卡下两台同一真实时刻的完整实亮前缀、失答后的同号续办、封存后值班端重开且两台离线的原册复领，并保留原发卡与散场结册回归。

## 启动

在项目根目录的三个终端分别运行以下命令。灯台各自使用数据库文件。值班台用自己的数据库保存谱稿、校样、发卡状态和结册。服务只监听 `127.0.0.1`。初始化只补建表和索引，同一场次用原数据库、灯台标识及端口配置重开即可保留已写数据。

```sh
python3 -B -m dispatch.http --db duty.sqlite3 --show qinghe --port 8010 --lamp alpha=8011 --lamp beta=8012 --short-pool 2
python3 -B -m lamp.http --db alpha.sqlite3 --show qinghe --lamp alpha --duty-port 8010 --port 8011
python3 -B -m lamp.http --db beta.sqlite3 --show qinghe --lamp beta --duty-port 8010 --port 8012
```

## 当天流程

1. 老师把 `sample.json` 的 `score` 对象发到 `POST /score_write`。每张卡的 `id` 在该修订中唯一，`section` 指向声明过的乐段，`voice` 为具名声部。整批合法才得到修订号与各卡出处。
2. 老师用修订号、选段和样例中的声部分派调用 `POST /preview`。拍位单位是整数拍，先按拍升序，同拍沿原稿顺序。开场段得到 A「吸气」、B「收声」、C「延长」，休息段得到空清单。只有候选卡需要解析分派。
3. 冻结校样可按号复读。当日修谱或重配声部可生成新校样，原校样的内容与灯台继续有效。
4. 值班员按原请求号和固定卡项调用 `POST /send`。服务先提交发卡单和投递任次，再向目标灯台发送。尚无可核实结果时按请求号查到 `pending`。
5. 灯台请求值班端读回已受理的投递事实，比较场次、原请求、卡项和本台目标。合法首次执行一次提交实际灯次和卡稿。灯次按场次及灯台的实际提交次序递增。
6. 短回报到达后，值班台沿该交换的连接上下文读取已经提交的实亮。普通失答后按原请求号及原参数再次发卡。提交前失答可以首次执行，提交后失答会复领原灯次。查单只有在核实后显示 `lit` 与灯次。
7. 领队请求结册。值班台针对本次读取的已结清单再次查实灯次和原稿出处。存在待查时返回欠查原号，待续办后重新申请。
8. 核齐后结册按灯台标识和实际灯次排序。领队按册号读取固定正文。即使甲台推迟 A、先亮 C，且随后另发新谱，原册仍按 C 再 A 保存当时的实亮。

## HTTP 接口

请求与成功响应均为 JSON。下表列出请求体字段或 GET 查询参数。POST 必须携带 JSON 请求体。

| 入口 | 字段 | 成功结果 |
| --- | --- | --- |
| 值班 `POST /score_write` | `show`, `sections` 字符串列表, `cues` 对象列表。卡项字段为 `id`, `section`, `voice`, `beat`, `text` | 201，`show`, `revision`, `sources` |
| 值班 `GET /revision` | `show`, `revision` | 200，修订中的乐段和原卡稿 |
| 值班 `POST /preview` | `show`, `revision`, `section`, `assignments` 声部到灯台的对象 | 201，`preview_id`、固定分派和 `cues` 有序清单 |
| 值班 `GET /preview` | `show`, `preview_id` | 200，固定校样原内容 |
| 值班 `POST /send` | `show`, `request_id`, `preview_id`, `cue_id`, `target`，可选 `transport` | 200，原单、固定 `cue` 与 `status`。`lit` 时另有 `actual_lamp` 和 `flash_number` |
| 值班 `GET /lookup` | `show`, `request_id` | 200，原单和已提交的查单状态 |
| 值班 `POST /close_book` | `show` | 200，`pending` 和欠查原号，或 `closed`、`book_id` 及 `entries` |
| 值班 `GET /read_book` | `show`, `book_id` | 200，原封存结册 |
| 值班 `POST /mark_pause` | `show`, `mark_id` | 200，该暂停号的待核状态，或含 `heads`、`entries` 的封存册；同号续办与复领固定同结果 |
| 值班 `GET /read_pause` | `show`, `mark_id` | 200，原暂停状态或原封存册；未知号 404，查询只读 |

例如，已生成编号 1 的开场校样后，向值班端发 `POST /send`，请求体为 `{"show":"qinghe","request_id":"U","preview_id":1,"cue_id":"A","target":"alpha"}`。普通同参重投使用同一请求体。可选的 `transport` 形如 `{"connection":"desk-alpha-2","short":1}`，用于显式选择交付交换。短号取从 0 起、大小为 `--short-pool` 的整数池。逻辑连接标识使用 ASCII 字母、数字、点、横线和下划线。同一连接内已绑定的短号归原请求，另一连接可同时使用同一短号。省略 `transport` 时，待查单沿用首次投递任次，已结清单可直接复领。

服务之间使用以下环回接口。`X-Delivery-Connection` 承载逻辑连接标识，普通同步回报沿发出投递的 HTTP 交换返回。转交迟到回报时保留原连接上下文。

| 入口 | 字段 | 结果 |
| --- | --- | --- |
| 灯台 `POST /execute` | 连接头，JSON `show`, `request_id`, `preview_id`, `cue`, `short` | 200，`{"short":0}` 形式的回报，值为该任次短号 |
| 值班 `GET /dispatch_fact` | `show`, `connection`, `short` | 已受理任次的 `show`, `request_id`, `preview_id`, `cue` |
| 值班 `POST /report` | 原连接头和只含 `short` 的回报正文 | 可匹配时返回原单状态，连接或正文不可用时为 `unverified` |
| 灯台 `GET /attempt_result` | `show`, `connection`, `short` | 已提交的该任次实亮记录 |
| 灯台 `GET /flash` | `show`, `number` | 当前台指定实际灯次的记录 |
| 灯台 `POST /pause_marker` | JSON `show`, `mark_id` | 200，扣住本台新首亮（TTL 自动放行）并回 `head`；同号重放 `replay` 为真 |
| 灯台 `GET /pause_head` | `show` | 200，当前台已提交实亮的截至灯次，无实亮为 0 |
| 灯台 `POST /pause_release` | JSON `show`, `mark_id` | 200，提前放行暂停扣持，返回 `released` |

错误响应包含 `error` 和 `message`。400 用于非法输入，包括负拍、非整数拍、布尔拍、缺拍位、谱稿引用未声明段和候选缺目标。404 用于找不到场次、修订、选段、固定卡项、原请求、实亮、暂停号或册号。409 用于同号异参、目标不符、任次归属冲突及无法匹配发卡事实。灯台暂时无法读取值班端的已受理事实时返回 503。投递失答、任次结果尚未能查实或领队暂时无法核对实亮时，值班端保留欠查状态。暂停取点失答或无法确认两台共同截面时保留 `pending` 待核，不改变任何原单核回状态，在线灯台继续普通首亮。未查实的请求没有成功灯次，也不会进入固定册页。
