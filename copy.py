import time
import random
import threading
import sys
import select
from datetime import datetime
from queue import PriorityQueue

# Deteksi platform untuk input non-blocking
try:
    import tty
    import termios
    _UNIX = True
except ImportError:
    import msvcrt
    _UNIX = False


# ===========================================================
# FUNGSI INPUT NON-BLOCKING
# Membaca input karakter per karakter menggunakan raw terminal
# mode. Jika refresh_event di-set (status teller berubah)
# sebelum user menekan Enter, langsung kembalikan None
# sebagai sinyal untuk mencetak ulang menu.
# ===========================================================

def _baca_unix(prompt, refresh_event):
    """Input non-blocking untuk Unix/Linux/Mac menggunakan tty raw mode + select."""
    sys.stdout.write(prompt)
    sys.stdout.flush()

    fd = sys.stdin.fileno()
    pengaturan_lama = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        buffer = ""
        while True:
            # Polling stdin dengan timeout 0.1 detik
            siap, _, _ = select.select([sys.stdin], [], [], 0.1)
            if siap:
                karakter = sys.stdin.read(1)
                if karakter in ('\r', '\n'):       # Enter
                    sys.stdout.write('\r\n')
                    sys.stdout.flush()
                    return buffer
                elif karakter in ('\x7f', '\b'):   # Backspace
                    if buffer:
                        buffer = buffer[:-1]
                        sys.stdout.write('\b \b')
                        sys.stdout.flush()
                elif karakter == '\x03':           # Ctrl+C
                    raise KeyboardInterrupt
                elif karakter == '\x04':           # Ctrl+D
                    raise EOFError
                else:
                    buffer += karakter
                    sys.stdout.write(karakter)
                    sys.stdout.flush()

            # Cek apakah status teller berubah
            if refresh_event.is_set():
                sys.stdout.write('\r\n')
                sys.stdout.flush()
                return None   # sinyal: cetak ulang menu
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, pengaturan_lama)


def _baca_windows(prompt, refresh_event):
    """Input non-blocking untuk Windows menggunakan msvcrt."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    buffer = ""
    while True:
        if msvcrt.kbhit():
            karakter = msvcrt.getwch()
            if karakter in ('\r', '\n'):
                sys.stdout.write('\n')
                sys.stdout.flush()
                return buffer
            elif karakter == '\x08':               # Backspace
                if buffer:
                    buffer = buffer[:-1]
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
            elif karakter == '\x03':               # Ctrl+C
                raise KeyboardInterrupt
            else:
                buffer += karakter
                sys.stdout.write(karakter)
                sys.stdout.flush()
        if refresh_event.is_set():
            sys.stdout.write('\n')
            sys.stdout.flush()
            return None
        time.sleep(0.05)


def baca_input(prompt, refresh_event):
    """Wrapper: pilih implementasi sesuai platform."""
    if _UNIX:
        return _baca_unix(prompt, refresh_event)
    else:
        return _baca_windows(prompt, refresh_event)


# ===========================================================
# KELAS NASABAH
# ===========================================================

class Nasabah:
    def __init__(self, nama, prioritas=2):
        """
        Prioritas:
        0 = VIP (Paling Tinggi)
        1 = Lansia/Disabilitas
        2 = Reguler (Biasa)
        """
        self.nama = nama
        self.prioritas = prioritas
        self.waktu_datang = datetime.now()
        self.id_unik = random.randint(1, 999)

    def __lt__(self, other):
        return self.prioritas < other.prioritas

    def __str__(self):
        jenis = {0: "VIP", 1: "Lansia", 2: "Reguler"}
        return f"[{jenis[self.prioritas]}] {self.nama} (ID:{self.id_unik})"


# ===========================================================
# KELAS TELLER
# ===========================================================

class Teller:
    def __init__(self, id_teller):
        self.id = id_teller
        self.status = "KOSONG"
        self.nasabah_dilayani = None
        self._lock = threading.Lock()

    def layani(self, nasabah, callback_selesai=None):
        """
        Menjalankan pelayanan di thread terpisah agar tidak
        memblokir loop utama. Status langsung jadi SIBUK
        sehingga tampilkan_status() bisa membacanya real-time.
        """
        def _proses():
            with self._lock:
                self.status = "SIBUK"
                self.nasabah_dilayani = nasabah

            durasi = random.randint(2, 5)
            print(f"\n   🟢 Teller-{self.id} mulai melayani {nasabah}... "
                  f"(Estimasi: {durasi} detik)")

            time.sleep(durasi)

            with self._lock:
                self.status = "KOSONG"
                self.nasabah_dilayani = None

            print(f"   🔴 Teller-{self.id} selesai melayani {nasabah}.\n")

            if callback_selesai:
                callback_selesai(nasabah, durasi)

        thread = threading.Thread(target=_proses, daemon=True)
        thread.start()
        return thread


# ===========================================================
# KELAS SISTEM BANK
# ===========================================================

class SistemBank:
    def __init__(self, jumlah_teller=2):
        self.antrian_nasabah = PriorityQueue()
        self.daftar_teller = [Teller(i + 1) for i in range(jumlah_teller)]
        self.statistik = {
            "total_nasabah": 0,
            "terlayani": 0,
            "total_waktu_tunggu": 0
        }
        self._statistik_lock = threading.Lock()
        self.file_log = open("log_bank.txt", "a")

    def log_kegiatan(self, pesan):
        waktu = datetime.now().strftime("%H:%M:%S")
        teks = f"[{waktu}] {pesan}\n"
        print(teks.strip())
        self.file_log.write(teks)

    def nasabah_datang(self, nama, prioritas=2):
        nasabah_baru = Nasabah(nama, prioritas)
        self.antrian_nasabah.put(nasabah_baru)
        with self._statistik_lock:
            self.statistik["total_nasabah"] += 1
        self.log_kegiatan(f"Nasabah {nasabah_baru} masuk antrian.")

    def proses_antrian(self):
        teller_kosong = [t for t in self.daftar_teller if t.status == "KOSONG"]

        if not teller_kosong:
            self.log_kegiatan("Semua teller sedang sibuk.")
            return

        if self.antrian_nasabah.empty():
            self.log_kegiatan("Antrian kosong, tidak ada yang diproses.")
            return

        nasabah = self.antrian_nasabah.get()
        waktu_tunggu = (datetime.now() - nasabah.waktu_datang).total_seconds()
        teller_pilih = teller_kosong[0]
        id_teller = teller_pilih.id

        def selesai(n, durasi):
            with self._statistik_lock:
                self.statistik["total_waktu_tunggu"] += waktu_tunggu
                self.statistik["terlayani"] += 1
            self.log_kegiatan(
                f"{n} selesai dilayani Teller-{id_teller}. "
                f"Waktu tunggu: {waktu_tunggu:.2f} dtk. Durasi: {durasi} dtk."
            )

        teller_pilih.layani(nasabah, callback_selesai=selesai)
        self.log_kegiatan(f"{nasabah} mulai dilayani Teller-{id_teller}.")

    def ada_teller_sibuk(self):
        return any(t.status == "SIBUK" for t in self.daftar_teller)

    def tampilkan_status(self):
        print("\n--- STATUS REAL-TIME ---")
        for t in self.daftar_teller:
            if t.status == "SIBUK":
                info = f"(Melayani: {t.nasabah_dilayani})"
            else:
                info = ""
            print(f"  Teller-{t.id}: [{t.status}] {info}")
        print(f"  Sisa Antrian : {self.antrian_nasabah.qsize()} orang")
        print("------------------------\n")

    def tampilkan_laporan_akhir(self):
        # Tunggu semua teller selesai sebelum cetak laporan
        for t in self.daftar_teller:
            while t.status == "SIBUK":
                time.sleep(0.5)

        with self._statistik_lock:
            avg_wait = (
                self.statistik["total_waktu_tunggu"] / self.statistik["terlayani"]
                if self.statistik["terlayani"] > 0 else 0
            )
            print("\n========================================")
            print("       LAPORAN AKHIR SIMULASI           ")
            print("========================================")
            print(f"  Total Nasabah Datang   : {self.statistik['total_nasabah']}")
            print(f"  Total Nasabah Terlayani: {self.statistik['terlayani']}")
            print(f"  Rata-rata Waktu Tunggu : {avg_wait:.2f} detik")
            print("========================================\n")

        self.file_log.close()


# ===========================================================
# MANAJER MENU
#
# Cara kerja sistem refresh:
# 1. Thread _monitor berjalan di background, memantau
#    perubahan status teller setiap 0.3 detik.
# 2. Saat status berubah, _monitor men-set _refresh_event.
# 3. baca_input() melakukan polling _refresh_event di antara
#    pembacaan karakter. Jika event di-set → kembalikan None.
# 4. Loop utama menerima None → cetak ulang menu baru.
#    Karena terminal dalam raw mode, tidak ada karakter
#    "sisa" yang mengganggu — setiap sesi input bersih.
# ===========================================================

class ManajerMenu:
    def __init__(self, bank: SistemBank):
        self.bank = bank
        self._refresh_event = threading.Event()
        self._stop = threading.Event()
        # Instance variable agar bisa disinkronkan dari _handle_normal
        # ketika kita yang memulai proses (bukan perubahan eksternal)
        self._status_monitor = False

    def _monitor(self):
        """
        Pantau perubahan status teller. Jika berubah,
        set _refresh_event agar baca_input() berhenti
        dan menu bisa dicetak ulang.
        """
        while not self._stop.is_set():
            time.sleep(0.3)
            status_sekarang = self.bank.ada_teller_sibuk()
            if status_sekarang != self._status_monitor:
                self._status_monitor = status_sekarang
                # Jeda singkat agar pesan teller sempat tercetak dulu
                time.sleep(0.2)
                self._refresh_event.set()

    def _cetak_menu(self):
        """Cetak menu sesuai kondisi teller, kembalikan prompt dan mode."""
        print("\n" + "=" * 45)
        if self.bank.ada_teller_sibuk():
            print("  ⏳ TELLER SEDANG BEKERJA...")
            print("=" * 45)
            print("  MENU:")
            print("  1. Lihat Status Bank")
            print("  2. Keluar & Lihat Laporan")
            print("=" * 45)
            return "Pilih Menu (1-2): ", True
        else:
            print("  MENU:")
            print("=" * 45)
            print("  1. Lihat Status Bank")
            print("  2. Nasabah Reguler Datang")
            print("  3. Nasabah VIP Datang")
            print("  4. Nasabah Lansia Datang")
            print("  5. Proses Antrian (Jalankan Teller)")
            print("  6. Keluar & Lihat Laporan")
            print("=" * 45)
            return "Pilih Menu (1-6): ", False

    def jalankan(self):
        t_monitor = threading.Thread(target=self._monitor, daemon=True)
        t_monitor.start()

        lanjut = True
        while lanjut:
            prompt, mode_sibuk = self._cetak_menu()
            self._refresh_event.clear()

            # Baca input — akan langsung kembali None jika status teller berubah
            pilihan = baca_input(prompt, self._refresh_event)

            if pilihan is None:
                # Status berubah di tengah input → cukup loop dan cetak menu baru
                continue

            pilihan = pilihan.strip()

            if mode_sibuk:
                lanjut = self._handle_sibuk(pilihan)
            else:
                lanjut = self._handle_normal(pilihan)

        self._stop.set()

    def _handle_sibuk(self, pilihan):
        if pilihan == '1':
            self.bank.tampilkan_status()
        elif pilihan == '2':
            return False
        else:
            print("❌ Pilihan tidak valid!")
        return True

    def _handle_normal(self, pilihan):
        if pilihan == '1':
            self.bank.tampilkan_status()

        elif pilihan == '2':
            # Gunakan input() biasa untuk nama (cooked mode sudah dipulihkan)
            nama = input("Nama Nasabah Reguler: ").strip()
            if nama:
                self.bank.nasabah_datang(nama, prioritas=2)

        elif pilihan == '3':
            nama = input("Nama Nasabah VIP: ").strip()
            if nama:
                self.bank.nasabah_datang(nama, prioritas=0)

        elif pilihan == '4':
            nama = input("Nama Nasabah Lansia: ").strip()
            if nama:
                self.bank.nasabah_datang(nama, prioritas=1)

        elif pilihan == '5':
            print("\n⏳ Memproses antrian...")
            for _ in range(len(self.bank.daftar_teller)):
                self.bank.proses_antrian()
            # Tunggu sebentar agar thread teller sempat men-set status SIBUK,
            # lalu sinkronkan _status_monitor. Dengan ini, monitor tidak akan
            # mendeteksi transisi False→True ini sebagai "perubahan baru",
            # sehingga menu mode-sibuk hanya tercetak sekali.
            time.sleep(0.05)
            self._status_monitor = self.bank.ada_teller_sibuk()

        elif pilihan == '6':
            return False

        else:
            print("❌ Pilihan tidak valid!")

        return True


# ===========================================================
# MAIN
# ===========================================================

if __name__ == "__main__":
    print("🏦 SIMULASI ANTRIAN BANK REALISTIS (PBL STRUKTUR DATA)")
    print("-----------------------------------------------------")

    bank = SistemBank(jumlah_teller=2)
    menu = ManajerMenu(bank)

    try:
        menu.jalankan()
    except KeyboardInterrupt:
        pass
    finally:
        bank.tampilkan_laporan_akhir()