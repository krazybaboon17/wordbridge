import reflex as rx
import urllib.parse
import random
import httpx
import asyncio
import time

GLOBAL_POOL = []
API_CACHE = {}

async def fetch_datamuse(url: str, client: httpx.AsyncClient):
    global API_CACHE
    if url in API_CACHE:
        return API_CACHE[url]
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            if len(API_CACHE) > 5000:
                API_CACHE.clear()
            API_CACHE[url] = data
            return data
    except Exception:
        pass
    return []


class State(rx.State):
    inputWord: str = ""
    previousWord: str = "water"
    feedback: str = ""
    targetWord: str = ""
    showInstructions: bool = False
    wordPath: list[str] = []
    showWinModal: bool = False
    proximityScore: int = 0
    lastProximityScore: int = 0
    proximityDirection: str = ""
    targetNeighborhood: dict[str, int] = {}
    hasWon: bool = False
    showCustomModal: bool = False
    customStart: str = ""
    customEnd: str = ""
    customError: str = ""

    @rx.var
    def score(self) -> int:
        return len(self.wordPath) - 1

    def setShowInstructions(self, val: bool):
        self.showInstructions = val

    def setShowWinModal(self, val: bool):
        self.showWinModal = val

    def openInstructions(self):
        self.showInstructions = True

    def closeInstructions(self):
        self.showInstructions = False

    def openCustomModal(self):
        self.showCustomModal = True
        self.customError = ""

    def closeCustomModal(self):
        self.showCustomModal = False
        self.customError = ""

    def setCustomStart(self, val: str):
        self.customStart = val

    def setCustomEnd(self, val: str):
        self.customEnd = val

    async def startCustomGame(self):
        start = self.customStart.lower().strip()
        end = self.customEnd.lower().strip()

        if not start or not end:
            self.customError = "Both fields are required."
            return
        if start == end:
            self.customError = "Start and end words must be different."
            return

        self.showCustomModal = False
        self.customError = ""
        self.inputWord = ""
        self.feedback = ""
        self.wordPath = [start]
        self.proximityScore = 0
        self.lastProximityScore = 0
        self.proximityDirection = ""
        self.showWinModal = False
        self.hasWon = False
        self.previousWord = start
        self.targetWord = end


        try:
            url = f"https://api.datamuse.com/words?ml={urllib.parse.quote(end)}&max=1000"
            async with httpx.AsyncClient(timeout=10.0) as client:
                nRes = await fetch_datamuse(url, client)
            self.targetNeighborhood = {item["word"]: item.get("score", 0) for item in nRes}
        except Exception:
            self.targetNeighborhood = {}

        self.proximityScore = self.getWordSimilarity(start)
        self.lastProximityScore = self.proximityScore


    async def resetGame(self):
        self.inputWord = ""
        self.feedback = ""
        self.wordPath = []
        self.proximityScore = 0
        self.lastProximityScore = 0
        self.proximityDirection = ""
        self.showWinModal = False
        self.hasWon = False

        await self.getWord()

    def getWordSimilarity(self, word: str) -> int:
        word = word.lower().strip()
        if word == self.targetWord.lower():
            return 100
        score = self.targetNeighborhood.get(word, 0)
        normalized = min(95, int((score / 80000) * 100)) if score > 0 else 0
        return normalized

    async def getWord(self):
        global GLOBAL_POOL
        try:
            if not GLOBAL_POOL:
                anchors = ["thing", "place", "concept", "world", "system", "life", "action"]
                async with httpx.AsyncClient(timeout=15.0) as client:
                    anchorResponses = await asyncio.gather(
                        *[fetch_datamuse(f"https://api.datamuse.com/words?ml={anchor}&max=300&md=f", client) for anchor in anchors]
                    )

                    pool = set()
                    for resp_data in anchorResponses:
                        for w in resp_data:
                            if "tags" in w and any(t.startswith("f:") and float(t[2:]) > 1.0 for t in w["tags"]):
                                pool.add(w["word"])

                    poolList = list(pool)
                    if len(poolList) < 20:
                        poolList = ["water", "fire", "earth", "air", "light", "dark", "sound", "time", "space", "nature"]
                    GLOBAL_POOL = poolList

            attempts = 0
            while attempts < 20:
                w1 = random.choice(GLOBAL_POOL)
                w2 = random.choice(GLOBAL_POOL)
                if w1 != w2:
                    self.previousWord = w1
                    self.targetWord = w2
                    break
                attempts += 1

            self.wordPath = [self.previousWord]
            self.feedback = ""
            self.hasWon = False

            neighborhoodUrl = f"https://api.datamuse.com/words?ml={urllib.parse.quote(self.targetWord)}&max=1000"
            async with httpx.AsyncClient(timeout=15.0) as client:
                nRes = await fetch_datamuse(neighborhoodUrl, client)
            self.targetNeighborhood = {item["word"]: item.get("score", 0) for item in nRes}

            self.proximityScore = self.getWordSimilarity(self.previousWord)
            self.lastProximityScore = self.proximityScore
            self.proximityDirection = ""

        except Exception:
            self.feedback = "Error starting game."

    def setInputWord(self, val):
        self.inputWord = val

    async def compareWord(self, key):
        if key != "Enter":
            return

        searchWord = self.inputWord.lower().strip()
        if not searchWord:
            return

        safeWord = urllib.parse.quote(self.previousWord)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                mlRes, trgRes, synRes = await asyncio.gather(
                    fetch_datamuse(f"https://api.datamuse.com/words?ml={safeWord}&max=1000", client),
                    fetch_datamuse(f"https://api.datamuse.com/words?rel_trg={safeWord}&max=1000", client),
                    fetch_datamuse(f"https://api.datamuse.com/words?rel_syn={safeWord}&max=1000", client),
                )

                validWords = (
                    {w["word"].lower() for w in mlRes} |
                    {w["word"].lower() for w in trgRes} |
                    {w["word"].lower() for w in synRes}
                )

                if searchWord == self.targetWord.lower():
                    isValid = searchWord in validWords

                    if not isValid:
                        relation = await fetch_datamuse(
                            f"https://api.datamuse.com/words?ml={safeWord}&sp={urllib.parse.quote(searchWord)}", client
                        )
                        if relation:
                            isValid = True

                    if not isValid:
                        w1, w2 = self.previousWord.lower(), searchWord
                        if w1 + "s" == w2 or w2 + "s" == w1 or w1 + "es" == w2 or w2 + "es" == w1:
                            isValid = True

                    if isValid:
                        self.wordPath.append(self.targetWord)
                        self.proximityScore = 100

                        self.feedback = "You Win"
                        self.showWinModal = True
                        self.hasWon = True
                        self.inputWord = ""
                        return
                    else:
                        self.feedback = "Too far from target!"
                        self.inputWord = ""
                        return

                isAssociated = searchWord in validWords
                if not isAssociated:
                    for vw in validWords:
                        if vw + "s" == searchWord or searchWord + "s" == vw or \
                           vw + "es" == searchWord or searchWord + "es" == vw:
                            isAssociated = True
                            break

                if isAssociated:
                    self.wordPath.append(searchWord)
                    self.previousWord = searchWord
                    self.inputWord = ""
                    self.feedback = "Correct"

                    self.lastProximityScore = self.proximityScore
                    self.proximityScore = self.getWordSimilarity(searchWord)


                    if self.proximityScore > self.lastProximityScore:
                        self.proximityDirection = "Closer ↑"
                    elif self.proximityScore < self.lastProximityScore:
                        self.proximityDirection = "Farther ↓"
                    else:
                        self.proximityDirection = "Steady →"
                else:
                    self.inputWord = ""
                    self.feedback = "No Association"
        except Exception:
            self.feedback = "API Error"





def index() -> rx.Component:
    return rx.box(
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title("How to Play WordBridge"),
                rx.dialog.description(
                    rx.vstack(
                        rx.text("Find a chain of associations to reach the target word."),
                        rx.text("Each word must 'vibe' with the current one to be accepted."),
                        rx.text("Type your word and press Enter to submit."),
                        rx.dialog.close(
                            rx.button(
                                "Got it!",
                                on_click=State.closeInstructions,
                                style={"background_color": "#1a1a1b", "color": "#fff", "margin_top": "1em"}
                            ),
                        ),
                        align="center",
                        spacing="4"
                    ),
                ),
                style={"max_width": "450px", "padding": "2em", "text_align": "center"}
            ),
            open=State.showInstructions,
            on_open_change=State.setShowInstructions,
        ),

        rx.dialog.root(
            rx.dialog.content(
                rx.vstack(
                    rx.heading("Linked In!", size="7", style={"color": "#1a1a1b"}),
                    rx.text(
                        "Final Score: ",
                        State.score.to_string(),
                        " steps",
                        size="4",
                        style={"font_weight": "bold", "color": "#6aaa64"}
                    ),
                    rx.divider(style={"background_color": "#d3d6da"}),
                    rx.text("YOUR PATH", size="2", style={"color": "#787c7e", "font_weight": "bold"}),
                    rx.box(
                        rx.hstack(
                            rx.foreach(
                                State.wordPath,
                                lambda word: rx.hstack(
                                    rx.text(word, style={"text_transform": "uppercase", "font_weight": "bold"}),
                                    rx.cond(
                                        word != State.targetWord,
                                        rx.icon(tag="arrow-right", size=16, color="#787c7e"),
                                        rx.box()
                                    ),
                                    spacing="2",
                                    align="center"
                                )
                            ),
                            wrap="wrap",
                            spacing="3",
                            justify="center"
                        ),
                        background_color="#f8f8f8",
                        padding="1.5em",
                        border_radius="8px",
                        border="1px solid #d3d6da",
                        width="100%"
                    ),

                    rx.dialog.close(
                        rx.button(
                            "New Game",
                            on_click=State.resetGame,
                            style={"background_color": "#1a1a1b", "color": "#fff", "margin_top": "1em", "width": "100%"}
                        ),
                    ),
                    spacing="4",
                    align="center"
                ),
                style={"max_width": "500px", "padding": "2em"}
            ),
            open=State.showWinModal,
            on_open_change=State.setShowWinModal,
        ),

        rx.dialog.root(
            rx.dialog.content(
                rx.vstack(
                    rx.heading("Custom Game", size="5", style={"color": "#1a1a1b"}),
                    rx.text(
                        "Enter a start word and a target word to create your own challenge.",
                        size="2",
                        style={"color": "#787c7e", "text_align": "center"}
                    ),
                    rx.divider(style={"background_color": "#d3d6da"}),
                    rx.vstack(
                        rx.text("START WORD", size="1", style={"font_weight": "bold", "color": "#787c7e", "letter_spacing": "0.08em"}),
                        rx.input(
                            placeholder="e.g. water",
                            value=State.customStart,
                            on_change=State.setCustomStart,
                            style={
                                "width": "100%",
                                "height": "44px",
                                "border_radius": "4px",
                                "border": "2px solid #d3d6da",
                                "font_family": "'Inter', sans-serif",
                                "font_weight": "600",
                                "font_size": "1em",
                                "text_align": "center",
                                "_focus": {"border": "2px solid #1a1a1b", "box_shadow": "none"}
                            }
                        ),
                        align="start",
                        spacing="1",
                        width="100%"
                    ),
                    rx.vstack(
                        rx.text("TARGET WORD", size="1", style={"font_weight": "bold", "color": "#787c7e", "letter_spacing": "0.08em"}),
                        rx.input(
                            placeholder="e.g. fire",
                            value=State.customEnd,
                            on_change=State.setCustomEnd,
                            style={
                                "width": "100%",
                                "height": "44px",
                                "border_radius": "4px",
                                "border": "2px solid #d3d6da",
                                "font_family": "'Inter', sans-serif",
                                "font_weight": "600",
                                "font_size": "1em",
                                "text_align": "center",
                                "_focus": {"border": "2px solid #1a1a1b", "box_shadow": "none"}
                            }
                        ),
                        align="start",
                        spacing="1",
                        width="100%"
                    ),
                    rx.cond(
                        State.customError != "",
                        rx.text(
                            State.customError,
                            size="2",
                            style={"color": "#ce3a3a", "font_weight": "600"}
                        ),
                        rx.box()
                    ),
                    rx.hstack(
                        rx.dialog.close(
                            rx.button(
                                "Cancel",
                                on_click=State.closeCustomModal,
                                variant="ghost",
                                style={"color": "#787c7e", "_hover": {"color": "#1a1a1b", "background_color": "transparent"}}
                            ),
                        ),
                        rx.button(
                            "Start Game",
                            on_click=State.startCustomGame,
                            style={"background_color": "#1a1a1b", "color": "#fff"}
                        ),
                        justify="end",
                        width="100%",
                        spacing="3"
                    ),
                    spacing="4",
                    align="center",
                    width="100%"
                ),
                style={"max_width": "420px", "padding": "2em"}
            ),
            open=State.showCustomModal,
            on_open_change=lambda v: State.closeCustomModal(),
        ),

        rx.vstack(
            rx.box(
                rx.heading(
                    "WordBridge",
                    size="7",
                    style={
                        "position": "absolute",
                        "left": "50%",
                        "transform": "translateX(-50%)",
                        "font_family": "'Inter', sans-serif",
                        "font_weight": "700",
                        "color": "#1a1a1b",
                        "letter_spacing": "-0.02em",
                    }
                ),
                rx.hstack(
                    rx.button(
                        "Custom",
                        on_click=State.openCustomModal,
                        size="1",
                        variant="ghost",
                        style={
                            "color": "#787c7e",
                            "font_weight": "600",
                            "_hover": {"background_color": "transparent", "color": "#1a1a1b"}
                        }
                    ),
                    rx.cond(
                        State.hasWon,
                        rx.button(
                            "New Game",
                            on_click=State.resetGame,
                            size="1",
                            variant="ghost",
                            style={
                                "color": "#6aaa64",
                                "font_weight": "700",
                                "_hover": {"background_color": "transparent", "color": "#1a1a1b"}
                            }
                        ),
                        rx.box()
                    ),
                    spacing="2",
                    position="absolute",
                    right="2em",
                    top="50%",
                    transform="translateY(-50%)",
                ),
                position="relative",
                width="100%",
                padding="1em 2em",
                border_bottom="1px solid #d3d6da",
                display="flex",
                align_items="center",
                justify_content="center",
                height="60px",
            ),

            rx.center(
                rx.vstack(
                    rx.vstack(
                        rx.text(
                            "TARGET WORD",
                            size="2",
                            style={
                                "font_family": "'Inter', sans-serif",
                                "font_weight": "600",
                                "color": "#787c7e",
                                "letter_spacing": "0.1em"
                            }
                        ),
                        rx.box(
                            rx.text(
                                State.targetWord,
                                size="6",
                                style={
                                    "font_family": "'Inter', sans-serif",
                                    "font_weight": "700",
                                    "color": "#ffffff",
                                    "text_transform": "uppercase"
                                }
                            ),
                            background_color="#6aaa64",
                            padding="0.6em 2em",
                            border_radius="4px",
                            box_shadow="0 2px 4px rgba(0,0,0,0.1)"
                        ),
                        align="center",
                        spacing="2"
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.text("PROXIMITY", size="1", style={"font_weight": "bold", "color": "#787c7e"}),
                            rx.spacer(),
                            rx.text(
                                State.proximityDirection,
                                size="1",
                                style={
                                    "font_weight": "bold",
                                    "color": rx.cond(State.proximityDirection.contains("Closer"), "#6aaa64", "#ce3a3a")
                                }
                            ),
                            width="250px"
                        ),
                        align="center",
                        spacing="2",
                        width="250px",
                    ),
                    rx.spacer(),
                    rx.vstack(
                        rx.text(
                            "CURRENT WORD",
                            size="2",
                            style={
                                "font_family": "'Inter', sans-serif",
                                "font_weight": "600",
                                "color": "#787c7e",
                                "letter_spacing": "0.1em"
                            }
                        ),
                        rx.box(
                            rx.text(
                                State.previousWord,
                                size="8",
                                style={
                                    "font_family": "'Inter', sans-serif",
                                    "font_weight": "800",
                                    "color": "#1a1a1b",
                                    "text_transform": "uppercase"
                                }
                            ),
                            padding="0.2em 0",
                            border_bottom="4px solid #1a1a1b"
                        ),
                        align="center",
                        spacing="2"
                    ),
                    rx.spacer(),
                    rx.input(
                        placeholder="Type a word...",
                        value=State.inputWord,
                        on_change=State.setInputWord,
                        on_key_down=State.compareWord,
                        style={
                            "width": "100%",
                            "max_width": "300px",
                            "height": "50px",
                            "border_radius": "4px",
                            "border": "2px solid #d3d6da",
                            "font_family": "'Inter', sans-serif",
                            "font_weight": "600",
                            "font_size": "1.1em",
                            "text_align": "center",
                            "_focus": {
                                "border": "2px solid #1a1a1b",
                                "box_shadow": "none"
                            }
                        }
                    ),
                    rx.vstack(
                        rx.text(
                            State.feedback,
                            size="5",
                            style={
                                "font_family": "'Inter', sans-serif",
                                "font_weight": "700",
                                "color": "#1a1a1b",
                                "margin_top": "1.5em",
                                "min_height": "1.2em",
                                "text_transform": "uppercase",
                                "letter_spacing": "0.05em"
                            }
                        ),
                        rx.cond(
                            State.feedback == "You Win",
                            rx.button(
                                "View Path",
                                on_click=State.setShowWinModal(True),
                                size="1",
                                variant="outline",
                                border="1px solid #d3d6da",
                                color="#787c7e",
                                cursor="pointer",
                                _hover={"color": "#1a1a1b", "border": "1px solid #1a1a1b"}
                            ),
                            rx.box()
                        ),
                        align="center",
                        spacing="2"
                    ),
                    width="100%",
                    align="center",
                    spacing="8",
                    padding_top="4em"
                ),
                width="100%"
            ),
            spacing="0",
            width="100%"
        ),
        width="100%",
        min_height="100vh",
        background_color="#ffffff"
    )


app = rx.App(
    stylesheets=[
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap"
    ]
)
app.add_page(index, on_load=[State.getWord, State.openInstructions])
