# io.github.ncr.spacewalk

Plugin do `omarchy-shell` zastępujący appkę Urevo przy bieżni **Urevo SpaceWalk 3S**.
Na barze pokazuje kroki dnia z paskiem postępu do celu; panel dokłada kalorie, czas,
dystans, godzinę osiągnięcia celu oraz sterowanie prędkością, nachyleniem i biegiem taśmy.

## Jak to działa

Dwie części gadają ze sobą przez strumień JSON, po jednej linii na aktualizację:

- `spacewalk-bridge.py` — trzyma połączenie Bluetooth z bieżnią (standard FTMS, serwis
  `0x1826`), pisze stan na stdout, czyta komendy ze stdin. Uruchamiany przez `uv`, więc
  `bleak` nie musi być instalowany w systemie.
- `Service.qml` / `BarWidget.qml` / `Panel.qml` — plugin shella. Serwis startuje razem
  z sesją i liczy kroki cały dzień, także z zamkniętym panelem.

Suma dnia leży w `~/.local/state/omarchy-spacewalk/RRRR-MM-DD.json`. Bieżnia zeruje
własne liczniki przy każdym starcie, więc most dodaje przyrosty do sumy dnia — kilka
sesji dziennie sumuje się w jedną liczbę.

## Instalacja

```bash
omarchy-shell shell rescanPlugins
omarchy plugin enable io.github.ncr.spacewalk
```

Po każdej zmianie w plikach pluginu: **`omarchy-restart-shell`**. Samo zapisanie pliku
przeładowuje most, ale nie kod widgetu ani panelu — zmiany w QML wchodzą dopiero po
restarcie shella. (`omarchy-refresh-shell` to co innego: przywraca domyślny pasek
i kasuje układ widgetów — nie używać.)

Podgląd stanu z terminala:

```bash
omarchy-shell spacewalk dump      # stan połączenia i liczniki dnia
omarchy-shell spacewalk start     # to samo co Start w panelu
omarchy-shell spacewalk stop
```

## Znalezienie bieżni

Bieżnia musi być pod prądem, a **appka Urevo w telefonie zamknięta** — przyjmuje jedno
połączenie naraz.

```bash
./probe.py                          # skan: szuka urządzenia z FTMS
./probe.py --address XX:XX:XX:XX:XX:XX   # pełna lista charakterystyk + podsłuch powiadomień
```

Adres wpisz w ustawieniach widgetu (Setup > Plugins) albo wprost do `~/.config/omarchy/shell.json`
przy wpisie `io.github.ncr.spacewalk`. Puste pole znaczy „szukaj po FTMS przy każdym połączeniu" —
działa, ale start trwa kilkanaście sekund dłużej.

## Ustawienia

| Pole | Domyślnie | Znaczenie |
|------|-----------|-----------|
| `address` | puste | adres Bluetooth bieżni |
| `dailyGoal` | 10000 | cel dzienny w krokach |
| `startSpeed` | 2.5 | prędkość ustawiana po starcie (km/h) |
| `startIncline` | 3 | nachylenie ustawiane po starcie |
| `strideMeters` | 0 | długość kroku; > 0 liczy kroki z dystansu, gdy bieżnia ich nie podaje |

## Obsługa

- klik w pigułkę — panel
- klik środkowym w pigułkę — start albo stop
- w panelu: strzałki przy prędkości (co 0,5 km/h) i nachyleniu (co 1), Start / Pauza / Zatrzymaj

Przy stojącej taśmie panel pokazuje wartości **po starcie** — bieżnia raportuje wtedy zera
i nie przyjmuje komend, więc zmiana strzałkami zapamiętuje cel, a most zadaje go, gdy taśma
się rozpędzi.

## Gdy przestaje się łączyć

SpaceWalk 3S bywa kapryśny przy wznawianiu połączenia. Most próbuje sam co 5 s, po
dziesięciu próbach co 30 s. Gdy to nie pomaga:

```bash
bluetoothctl disconnect <adres>
pkill -f spacewalk-bridge.py        # serwis podniesie most po ~10 s
```

Most można też uruchomić ręcznie i patrzeć, co pisze:

```bash
uv run --script ~/.config/omarchy/plugins/io.github.ncr.spacewalk/spacewalk-bridge.py --address <adres>
```

Komendy wpisuje się do jego stdin: `start`, `stop`, `pause`, `speed 2.5`, `incline 3`,
`reset-day`, `ping`.

## Kroki

Standardowy pakiet FTMS nie ma pola „kroki", ale SpaceWalk 3S dopisuje własny licznik
w wolnym miejscu pakietu — szczegóły w [docs/gatt-dump.md](docs/gatt-dump.md). Plugin czyta
go wprost, więc kroki są te same, które pokazuje appka producenta, razem z jej wykrywaniem
zejścia z taśmy.

Ustawienie `strideMeters` > 0 przełącza na liczenie z dystansu — zapas na wypadek innej
bieżni, przy tej niepotrzebny.

## Historia sprzed pluginu

Dni od 30 czerwca do 31 sierpnia 2026 pochodzą z eksportu Apple Health — appka UREVO
zapisywała tam kroki, dystans i kalorie z bieżni, po jednym rekordzie na dzień z przedziałem
czasu. Te pliki mają `"source": "urevo-health"`; czas marszu jest w nich długością przedziału,
jaki zapisała appka, więc zawiera przerwy i jest odrobinę dłuższy niż czas ruchu taśmy.

31 sierpnia ma sumę obu źródeł: appka chodziła rano (10 015 kroków, 8:26–10:39), plugin
zapisał popołudniowy test (39 kroków), przejścia się nie nakładają.

## Bieżnia zasypia

Bieżnia rozgłasza się tylko przez chwilę po włączeniu zasilania. Most skanuje bez przerwy
i bierze ją, gdy się odezwie, ale jeśli przegapi to okno, trzeba pstryknąć wyłącznikiem.

Telefon z appką Urevo wygrywa wyścig o połączenie — gdy się podłączy, bieżnia znika dla
komputera. Na czas pracy z pluginem wyłącz Bluetooth w telefonie.

## Apple Health

Przejścia trafiają do Zdrowia na iPhonie przez Skróty — most wystawia je pod adresem
z Tailscale. Instrukcja: [docs/apple-health.md](docs/apple-health.md).
