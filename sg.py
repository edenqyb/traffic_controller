import queue
import serial
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk

N, COLS = 24, 6
ROWS = N // COLS

COLORS = {"1": "#9e2624", "2": "#ecd363", "3": "#458248",
          "4": "#9e2624", "5": "#ecd363", "6": "#458248"}
NAMES = {"1": "Red", "2": "Yellow", "3": "Green",
         "4": "Flash Red", "5": "Flash Yellow", "6": "Flash Green"}
FLASHING = {"4", "5", "6"}

BG, PANEL, TILE_OFF, TEXT = "#292c37", "#2b2d31", "#3a3c42", "#e6e6e6"
TILE_W, TILE_H, GAP = 88, 64, 8


def build_frame(states: list[str]) -> bytes:
    assert len(states) == N, f"need exactly {N} signal groups, got {len(states)}"
    assert all(s in "123456" for s in states), "states must be 1-6"
    frame = b"S%" + b"\x00" * 3 + "".join(states).encode("ascii") + b"\x00" * 2 + b"E"
    assert len(frame) == 32
    return frame


def send_frame(frame: bytes, mode: str, ip: str, port: int, com: str) -> str:
    if mode == "serial":
        with serial.Serial(com, baudrate=57600, timeout=1) as ser:
            ser.write(frame)
            ser.flush()
            data = ser.read(1024)
            return f"reply: {data.hex(' ')}" if data else "sent, no reply"
    if mode == "tcp":
        with socket.create_connection((ip, port), timeout=3) as s:
            s.sendall(frame)
            s.settimeout(1)
            data = b""
            try:
                while chunk := s.recv(1024):
                    data += chunk
            except socket.timeout:
                pass
            return f"reply: {data.hex(' ')}" if data else "sent, no reply"
    if mode == "udp":
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1)
            s.sendto(frame, (ip, port))
            try:
                data, _ = s.recvfrom(1024)
                return f"reply: {data.hex(' ')}"
            except socket.timeout:
                return "sent (timeout)"
    raise ValueError("invalid mode")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Signal Group Controller")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.q: queue.Queue = queue.Queue()

        self.states = ["1"] * N
        self.brush = "3"
        self.blink_on = True
        self.brush_widgets: dict[str, tk.Label] = {}

        self._style()
        self._build_connection()
        self._build_palette()
        self._build_canvas()
        self._build_presets()
        self._build_send()
        self._build_log()

        self.select_brush("3")
        self.on_mode_change()
        self.redraw()
        self.after(100, self.poll)
        self.after(500, self.tick)

    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL)
        st.configure("TLabel", background=BG, foreground=TEXT)
        st.configure("TFrame", background=BG)
        st.configure("Card.TLabelframe", background=BG, foreground="#9aa0a6")
        st.configure("Card.TLabelframe.Label", background=BG, foreground="#9aa0a6")
        st.configure("TRadiobutton", background=BG, foreground=TEXT)
        st.map("TRadiobutton", background=[("active", BG)])
        st.configure("TEntry", fieldbackground=PANEL, foreground=TEXT)
        st.configure("TButton", padding=6, background=PANEL, foreground=TEXT)
        st.map("TButton", background=[("active", "#3a3c42")])
        st.configure("Send.TButton", padding=10, font=("Segoe UI", 11, "bold"),
                     background="#1f4179", foreground="white")
        st.map("Send.TButton", background=[("active", "#4766a8"), ("disabled", "#3a3c42")])

    def _card(self, title):
        f = ttk.LabelFrame(self, text=title, style="Card.TLabelframe", padding=10)
        f.pack(fill="x", padx=12, pady=(10, 0))
        return f

    def _build_connection(self):
        f = self._card("Connection")
        self.mode = tk.StringVar(value="tcp")
        top = ttk.Frame(f)
        top.pack(fill="x")
        for m in ("tcp", "udp", "serial"):
            ttk.Radiobutton(top, text=m.upper(), variable=self.mode, value=m,
                            command=self.on_mode_change).pack(side="left", padx=(0, 14))

        self.ip = tk.StringVar(value="192.168.100.40")
        self.port = tk.StringVar(value="5001")
        self.com = tk.StringVar(value="COM3")

        self.net_row = ttk.Frame(f)
        ttk.Label(self.net_row, text="IP").pack(side="left")
        ttk.Entry(self.net_row, textvariable=self.ip, width=16).pack(side="left", padx=(4, 12))
        ttk.Label(self.net_row, text="Port").pack(side="left")
        ttk.Entry(self.net_row, textvariable=self.port, width=7).pack(side="left", padx=4)

        self.ser_row = ttk.Frame(f)
        ttk.Label(self.ser_row, text="Port").pack(side="left")
        ttk.Entry(self.ser_row, textvariable=self.com, width=22).pack(side="left", padx=4)
        ttk.Label(self.ser_row, text="57600 baud", foreground="#9aa0a6").pack(side="left", padx=8)

    def _build_palette(self):
        f = self._card("1. Pick a color")
        row = ttk.Frame(f)
        row.pack()
        for code in "123456":
            lbl = tk.Label(row, text=NAMES[code], bg=COLORS[code], width=11, pady=8,
                           fg="black" if code in "2 5" or code in "25" else "white",
                           font=("Segoe UI", 9, "bold"), cursor="hand2",
                           highlightthickness=3, highlightbackground=BG)
            lbl.grid(row=0, column=int(code) - 1, padx=3)
            lbl.bind("<Button-1>", lambda e, c=code: self.select_brush(c))
            self.brush_widgets[code] = lbl

    def _build_canvas(self):
        f = self._card("2. Click or drag over signal groups to paint")
        w = COLS * (TILE_W + GAP) + GAP
        h = ROWS * (TILE_H + GAP) + GAP
        self.canvas = tk.Canvas(f, width=w, height=h, bg=BG, highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self.paint)
        self.canvas.bind("<B1-Motion>", self.paint)
        self.canvas.bind("<Button-3>", self.pick_color)
        self.hex_var = tk.StringVar()
        tk.Label(f, textvariable=self.hex_var, bg=BG, fg="#6b7280",
                 font=("Consolas", 8), wraplength=w, justify="left").pack(anchor="w", pady=(6, 0))

    def _build_presets(self):
        f = self._card("Quick set")
        row = ttk.Frame(f)
        row.pack(fill="x")
        presets = [
            ("Green, Yellow, rest Red", ["3", "2"] + ["1"] * 22),
            ("Yellow, Green, rest Red", ["2", "3"] + ["1"] * 22),
            ("All Red", ["1"] * N),
        ]
        for text, states in presets:
            ttk.Button(row, text=text, command=lambda s=states: self.set_all(s)).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Fill with selected", command=lambda: self.set_all([self.brush] * N)).pack(side="right")

    def _build_send(self):
        f = ttk.Frame(self)
        f.pack(fill="x", padx=12, pady=10)
        self.send_btn = ttk.Button(f, text="Send", style="Send.TButton", command=self.on_send)
        self.send_btn.pack(fill="x")
        self.bind("<Return>", lambda e: self.on_send())

    def _build_log(self):
        f = ttk.Frame(self)
        f.pack(fill="both", padx=12, pady=(0, 12))
        self.log = tk.Text(f, height=7, width=70, bg=PANEL, fg=TEXT, relief="flat",
                           font=("Consolas", 9), state="disabled", padx=8, pady=6)
        self.log.pack(fill="both")
        self.log.tag_config("ok", foreground="#4ade80")
        self.log.tag_config("err", foreground="#f87171")
        self.log.tag_config("info", foreground="#9aa0a6")

    # ---------- behavior ----------
    def on_mode_change(self):
        self.net_row.pack_forget()
        self.ser_row.pack_forget()
        (self.ser_row if self.mode.get() == "serial" else self.net_row).pack(fill="x", pady=(8, 0))

    def select_brush(self, code: str):
        self.brush = code
        for c, w in self.brush_widgets.items():
            w.configure(highlightbackground="white" if c == code else BG)

    def index_at(self, x, y):
        col, row = (x - GAP) // (TILE_W + GAP), (y - GAP) // (TILE_H + GAP)
        if not (0 <= col < COLS and 0 <= row < ROWS):
            return None
        if (x - GAP) % (TILE_W + GAP) > TILE_W or (y - GAP) % (TILE_H + GAP) > TILE_H:
            return None  # in the gap
        return row * COLS + col

    def paint(self, e):
        i = self.index_at(e.x, e.y)
        if i is not None and self.states[i] != self.brush:
            self.states[i] = self.brush
            self.redraw()

    def pick_color(self, e):
        i = self.index_at(e.x, e.y)
        if i is not None:
            self.select_brush(self.states[i])

    def set_all(self, states):
        self.states = list(states)
        self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        for i, code in enumerate(self.states):
            r, c = divmod(i, COLS)
            x = GAP + c * (TILE_W + GAP)
            y = GAP + r * (TILE_H + GAP)
            lit = code not in FLASHING or self.blink_on
            fill = COLORS[code] if lit else TILE_OFF
            self.canvas.create_rectangle(x, y, x + TILE_W, y + TILE_H, fill=fill,
                                         outline=COLORS[code] if code in FLASHING else fill, width=2)
            dark_text = code in "25" and lit
            fg = "black" if dark_text else "white"
            self.canvas.create_text(x + TILE_W / 2, y + 22, text=f"SG{i + 1}", fill=fg,
                                    font=("Segoe UI", 11, "bold"))
            self.canvas.create_text(x + TILE_W / 2, y + 44, text=NAMES[code], fill=fg,
                                    font=("Segoe UI", 8))
        self.hex_var.set("frame: " + build_frame(self.states).hex(" "))

    def tick(self):
        self.blink_on = not self.blink_on
        if any(s in FLASHING for s in self.states):
            self.redraw()
        self.after(500, self.tick)

    def write(self, msg: str, tag="info"):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def on_send(self):
        if str(self.send_btn["state"]) == "disabled":
            return
        try:
            frame = build_frame(self.states)
            port = int(self.port.get())
        except (AssertionError, ValueError) as e:
            return self.write(f"error: {e}", "err")
        self.write(f"sending via {self.mode.get()}...", "info")
        self.send_btn.configure(state="disabled", text="Sending...")
        args = (frame, self.mode.get(), self.ip.get(), port, self.com.get())
        threading.Thread(target=self.worker, args=args, daemon=True).start()

    def worker(self, *args):
        try:
            self.q.put((send_frame(*args), "ok"))
        except Exception as e:
            self.q.put((f"error: {e}", "err"))

    def poll(self):
        try:
            while True:
                msg, tag = self.q.get_nowait()
                self.write(msg, tag)
                self.send_btn.configure(state="normal", text="Send")
        except queue.Empty:
            pass
        self.after(100, self.poll)


if __name__ == "__main__":
    App().mainloop()