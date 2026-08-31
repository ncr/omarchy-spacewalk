# ncr.treadmill

Plugin do `omarchy-shell` zastępujący appkę Urevo przy bieżni **Urevo SpaceWalk 3S**.
Na barze pokazuje kroki dnia z paskiem postępu do celu; panel dokłada kalorie, czas,
dystans, godzinę osiągnięcia celu oraz sterowanie prędkością, nachyleniem i biegiem taśmy.

## Jak to działa

Dwie części gadają ze sobą przez strumień JSON, po jednej linii na aktualizację:

- `treadmill-bridge.py` — trzyma połączenie Bluetooth z bieżnią (standard FTMS, serwis
  `0x1826`), pisze stan na stdout, czyta komendy ze stdin. Uruchamiany przez `uv`, więc
  `bleak` nie musi być instalowany w systemie.
- `Service.qml` / `BarWidget.qml` / `Panel.qml` — plugin shella. Serwis startuje razem
  z sesją i liczy kroki cały dzień, także z zamkniętym panelem.

Suma dnia leży w `~/.local/state/omarchy-treadmill/RRRR-MM-DD.json`. Bieżnia zeruje
własne liczniki przy każdym starcie, więc most dodaje przyrosty do sumy dnia — kilka
sesji dziennie sumuje się w jedną liczbę.

## Instalacja

```bash
omarchy-shell shell rescanPlugins
omarchy plugin enable ncr.treadmill
```

## Znalezienie bieżni

Bieżnia musi być pod prądem, a **appka Urevo w telefonie zamknięta** — przyjmuje jedno
połączenie naraz.

```bash
./probe.py                          # skan: szuka urządzenia z FTMS
./probe.py --address XX:XX:XX:XX:XX:XX   # pełna lista charakterystyk + podsłuch powiadomień
```

Adres wpisz w ustawieniach widgetu (Setup > Plugins) albo wprost do `~/.config/omarchy/shell.json`
przy wpisie `ncr.treadmill`. Puste pole znaczy „szukaj po FTMS przy każdym połączeniu" —
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

## Gdy przestaje się łączyć

SpaceWalk 3S bywa kapryśny przy wznawianiu połączenia. Most próbuje sam co 5 s, po
dziesięciu próbach co 30 s. Gdy to nie pomaga:

```bash
bluetoothctl disconnect <adres>
pkill -f treadmill-bridge.py        # serwis podniesie most po ~10 s
```

Most można też uruchomić ręcznie i patrzeć, co pisze:

```bash
uv run --script ~/.config/omarchy/plugins/ncr.treadmill/treadmill-bridge.py --address <adres>
```

Komendy wpisuje się do jego stdin: `start`, `stop`, `pause`, `speed 2.5`, `incline 3`,
`reset-day`, `ping`.

## Znane ograniczenie

Standardowy pakiet danych bieżni FTMS nie zawiera pola „kroki". Jeśli bieżnia wystawia je
własną charakterystyką, znajdzie ją `probe.py` i wskazuje się ją mostowi przez
`--steps-uuid`. Bez tego kroki liczą się z dystansu (`strideMeters`), co znaczy, że
zejście z taśmy przy kręcącym się pasie nadal dolicza kroki.
