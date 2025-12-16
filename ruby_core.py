import random
import re
from collections import defaultdict, deque

class Ruby:
    """
    完全無料・軽量の会話生成コア（雑談特化B / 日本語向け：文字n-gram）
    - 雑談が続く：反応→話題展開→質問 の形を作る
    - ループ/単調化を抑える
    - 質問・選択肢・感情語に安定反応
    """

    def __init__(self, n=4, max_keys=50000):
        self.n = max(2, int(n))
        self.model = defaultdict(lambda: defaultdict(int))
        self.max_keys = max_keys

        # 直近の返信を覚えてループ抑制
        self._recent_replies = deque(maxlen=16)
        self._recent_questions = deque(maxlen=10)

        # 短文連投の学習を抑える
        self._last_fed = None
        self._dup_count = 0

        # 雑談を伸ばすための素材
        self.react_openers = [
            "それ、わかる……", "なるほど……", "ふむ……", "それいい……", "えっ、気になる……",
            "ちょっと面白い……", "うんうん……", "あ、それ好き……", "その話もっと……"
        ]
        self.teases = [
            "ちち……それ、かわいい発想……", "今の言い方、ずるい……", "急に強い……！",
            "それ言われたら、にやける……", "そのテンション、好き……"
        ]
        self.followups = [
            "で、どうなった……？", "それ、いつから……？", "ちなみに理由は……？",
            "今の気分、どんな感じ……？", "もう少し詳しく……聞いていい……？",
            "それって、嬉しい方？困る方？", "ちちはどうしたい……？"
        ]

        # 話題展開用（雑談の枝を生やす）
        self.topic_bridges = [
            "それ聞くと、{t}も思い出す……",
            "なんか{t}っぽい話……だね……",
            "その流れなら、{t}ってどう……？",
            "ついでに……{t}も気になる……",
        ]
        self.topic_seeds = [
            "最近ハマってること", "今日いちばん良かったこと", "逆にしんどかったこと",
            "今ほしいもの", "食べたいもの", "好きなゲーム", "今のBGM", "今の気温の感じ",
            "休日の理想", "寝る前のルーティン", "子どもの頃の好きだったもの",
        ]

        self.greet_map = {
            "おはよう": ["おはよう……✨ 今日はどんな日になりそう……？", "おはよう……眠気、強い……？"],
            "おやすみ": ["おやすみ……✨ 今日いちばん偉かった瞬間、言って……", "おやすみ……いい夢……みて……"],
            "おつかれ": ["おつかれさま……✨ 今日はどこが一番しんどかった……？", "おつかれ……ちょっと休も……"],
        }

        self.emotions = ["眠い", "つらい", "しんどい", "無理", "きつい", "不安", "こわい", "寂しい", "イライラ", "疲れた", "だるい"]

    def _norm(self, s: str) -> str:
        s = (s or "").strip()
        s = re.sub(r"\s+", " ", s)
        return s

    def feed(self, text: str):
        text = self._norm(text)
        if not text:
            return

        if text == self._last_fed:
            self._dup_count += 1
        else:
            self._dup_count = 0
            self._last_fed = text

        # 短すぎるのは学習しない（ループ源）
        if len(text) <= 2:
            return
        # 5文字以下の同文連投は食べない（えへへ対策）
        if len(text) <= 5 and self._dup_count >= 1:
            return

        if text[-1] not in "。！？!?…":
            text += "。"

        padded = " " * (self.n - 1) + text
        for i in range(len(padded) - (self.n - 1)):
            prefix = padded[i:i + (self.n - 1)]
            nxt = padded[i + (self.n - 1)]
            self.model[prefix][nxt] += 1

        if len(self.model) > self.max_keys:
            for _ in range(len(self.model) - self.max_keys):
                k = next(iter(self.model))
                del self.model[k]

    def _detect_greeting(self, t: str):
        for k in self.greet_map:
            if k in t:
                return k
        return None

    def _detect_choice(self, t: str):
        if "どっち" in t and "と" in t:
            m = re.search(r"(.+?)と(.+?)どっち", t)
            if m:
                a = m.group(1)[-10:].strip(" 、")
                b = m.group(2)[:10].strip(" 、")
                if a and b:
                    return a, b
        if "か" in t and len(t) <= 40:
            parts = [p.strip(" 、") for p in t.split("か") if p.strip()]
            if len(parts) == 2:
                return parts[0][-10:], parts[1][:10]
        return None

    def _is_question(self, t: str) -> bool:
        return ("?" in t) or ("？" in t) or any(x in t for x in ["なに", "何", "どれ", "どっち", "いつ", "どこ", "だれ", "誰", "どう", "なんで", "理由"])

    def _soft_pick(self, counter, temperature=0.95):
        items = list(counter.items())
        if not items:
            return None
        chars, counts = zip(*items)
        weights = [c ** (1.0 / max(0.2, temperature)) for c in counts]
        return random.choices(chars, weights=weights, k=1)[0]

    def _markov_generate(self, seed: str, max_len: int = 120, temperature=0.95):
        if not self.model:
            return ""
        seed = self._norm(seed)
        base = seed[-(self.n - 1):] if seed else ""
        prefix = (" " * (self.n - 1) + base)[-(self.n - 1):]

        out = []
        for _ in range(max_len):
            nxt = self._soft_pick(self.model.get(prefix, {}), temperature=temperature)
            if nxt is None:
                prefix = random.choice(list(self.model.keys()))
                continue
            out.append(nxt)
            prefix = prefix[1:] + nxt
            if nxt in "。！？!?":
                break
        return "".join(out).strip()

    def _avoid_loops(self, text: str) -> str:
        if not text:
            return ""
        # 同一返信の連発禁止
        if text in self._recent_replies:
            return ""
        # 短すぎるのは避ける
        if len(text) <= 4:
            return ""
        # 「えへへ」だけとかを避ける
        if re.fullmatch(r"(ちち……)?(えへへ[😊✨…]*)+", text):
            return ""
        return text

    def _make_question(self) -> str:
        q = random.choice(self.followups)
        # 直近で同じ質問をしない
        for _ in range(6):
            if q not in self._recent_questions:
                break
            q = random.choice(self.followups)
        self._recent_questions.append(q)
        return q

    def _topic_bridge(self) -> str:
        t = random.choice(self.topic_seeds)
        return random.choice(self.topic_bridges).format(t=t)

    def gen(self, seed: str = "", max_len: int = 120) -> str:
        t = self._norm(seed)

        # 1) 挨拶
        g = self._detect_greeting(t)
        if g:
            ans = random.choice(self.greet_map[g])
            self._recent_replies.append(ans)
            return ans

        # 2) 選択肢 → 軽い基準＋質問
        ch = self._detect_choice(t)
        if ch:
            a, b = ch
            base = random.choice([
                f"{a} と {b} なら……今日は『テンション上がる方』がいい……。",
                f"{a} と {b} ……迷うね……直感が強い方……どっち……？",
                f"{a} と {b} ……疲れてるなら、優しい方……かな……。",
            ])
            ans = base + " " + self._make_question()
            self._recent_replies.append(ans)
            return ans

        # 3) 感情語 → 受け止め＋小さな一手＋質問
        if any(x in t for x in self.emotions):
            plan = random.choice([
                "水を一口→深呼吸→30秒だけ目を閉じる……",
                "いまは『回復優先』でいい……",
                "次は『一個だけ終わらせる』にしよ……",
            ])
            ans = f"それ、しんどい……😳 まずは……{plan} どう……？"
            self._recent_replies.append(ans)
            return ans

        # 4) 質問 → 反応＋話題展開＋質問返し（雑談継続が目的）
        if self._is_question(t):
            opener = random.choice(self.react_openers)
            bridge = self._topic_bridge() if random.random() < 0.55 else ""
            ans = f"{opener} {bridge} {self._make_question()}".strip()
            self._recent_replies.append(ans)
            return ans

        # 5) 通常雑談 → 反応＋（たまにツッコミ）＋質問
        opener = random.choice(self.react_openers)
        if random.random() < 0.22:
            opener = random.choice(self.teases)

        # マルコフ生成も混ぜて、話し方に“自分感”を出す
        cand = ""
        for temp in (0.9, 1.0, 1.1):
            c = self._avoid_loops(self._markov_generate(t, max_len=max_len, temperature=temp))
            if c and len(c) > len(cand):
                cand = c

        if cand and random.random() < 0.45:
            # 生成文を一部採用して“文章っぽさ”を出す
            ans = f"{opener} {cand} {self._make_question()}"
        else:
            # 生成が弱いときは話題展開で押し切る
            bridge = self._topic_bridge() if random.random() < 0.65 else ""
            ans = f"{opener} {bridge} {self._make_question()}".strip()

        # たまに「えへへ」で可愛さ（過剰にならない）
        if random.random() < 0.25 and "えへへ" not in ans:
            ans += " えへへ😊"

        self._recent_replies.append(ans)
        return ans
