import random
from collections import defaultdict, Counter

class Ruby:
    def __init__(self, n=4):
        self.n = n
        self.bos = "⟪"; self.eos = "⟫"
        self.model = defaultdict(Counter)

    def feed(self, text):
        s = self.bos*(self.n-1) + text + self.eos
        for i in range(len(s)-(self.n-1)):
            k = s[i:i+self.n-1]
            self.model[k][s[i+self.n-1]] += 1

    def gen(self, seed="", max_len=80):
        if not self.model: return "……ちち……えへへ"
        k = (self.bos*(self.n-1)+seed)[-(self.n-1):]
        out=[]
        for _ in range(max_len):
            c = self.model.get(k)
            if not c:
                k = random.choice(list(self.model.keys()))
                c = self.model[k]
            ch = random.choice(list(c.elements()))
            if ch==self.eos: break
            out.append(ch); k=(k+ch)[-(self.n-1):]
        return "".join(out)
