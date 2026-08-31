# Co wystawia Urevo SpaceWalk 3S

Zebrane `probe.py` 2026-08-31 z prawdziwego marszu. Urządzenie: `54:50:00:47:91:EB`,
nazwa `URTM024`, producent UREVO, firmware V90.08.12, hardware V002.

## Serwisy

| Serwis | Co to |
|---|---|
| `0x1826` Fitness Machine | to, z czego korzysta plugin |
| `0x180a` Device Information | nazwa, model, wersje |
| `0xfff0` | własny protokół Urevo (`fff1` notify, `fff2` write) |
| `0xfee0` | Huami (Amazfit) — nieużywany |
| `5833ff01-9b8b-5191-6142-22a4536ef123` | własny, nieużywany |

## Fitness Machine

| Charakterystyka | Odczyt | Znaczenie |
|---|---|---|
| `0x2acc` Feature | `5c 16 00 00 03 00 00 00` | pola danych + **cele: prędkość i nachylenie wspierane** |
| `0x2ad4` Supported Speed Range | `64 00 58 02 0a 00` | 1,0 – 6,0 km/h, krok 0,1 |
| `0x2ad5` Supported Inclination Range | `00 00 5a 00 0a 00` | 0 – 9, krok 1 |
| `0x2acd` Treadmill Data | notify co 1 s | patrz niżej |
| `0x2ad9` Control Point | write + indicate | sterowanie |
| `0x2ada` Machine Status | notify | zmiany stanu maszyny |
| `0x2ad3` Training Status | notify | stan treningu |

## Pakiet Treadmill Data — 26 bajtów, flagi `9c 25`

Flagi `0x259c` ustawiają bity 2, 3, 4, 7, 8, 10 **i 13**. Bit 13 nie istnieje
w specyfikacji FTMS — Urevo dopisał w tym miejscu licznik kroków.

| Bajty | Pole | Przykład z marszu |
|---|---|---|
| 0–1 | flagi | `9c 25` |
| 2–3 | prędkość, setne km/h | `fa 00` → 2,50 |
| 4–6 | dystans, m (rozdzielczość 10 m) | `64 00 00` → 100 |
| 7–8 | nachylenie, dziesiąte % | `1e 00` → 3,0 |
| 9–10 | kąt rampy | `00 00` |
| 11–14 | przewyższenie w górę i w dół | zera |
| 15–16 | kalorie | `06 00` → 6 |
| 17–19 | kcal/h, kcal/min | zera |
| 20 | tętno | `00` |
| 21–22 | czas, s | `95 00` → 149 |
| **23–25** | **kroki, uint24 — dodatek Urevo** | `b3 00 00` → **179** |

Dowód, że to kroki, a nie drugi zegar: przez 130 s marszu licznik urósł do 179, czyli
1,36/s, podczas gdy czas w tym samym pakiecie szedł równo 1,0/s. Wychodzi 0,56 m na krok
przy 100 m dystansu — tyle, ile daje wolny marsz przy 2,5 km/h.

## Sterowanie — co działa i czego się spodziewać

Sprawdzone odpowiedzi z `0x2ad9`: `80 00 01` (przejęcie sterowania), `80 07 01` (start),
`80 02 01` (prędkość), `80 03 01` (nachylenie) — wszystkie przyjęte.

**Prędkość i nachylenie zadane od razu po starcie przepadają bez odpowiedzi.** Bieżnia
rozpędza się najpierw do 1 km/h i dopiero wtedy przyjmuje cele. Most odczekuje 8 s
i ponawia do czterech razy, aż odczyt zgodzi się z zadaną wartością.

**Stojąca taśma nie przyjmuje żadnych komend prędkości ani nachylenia** — wszystkie osiem
przypadków „brak odpowiedzi na 0x03" w logu to komendy wysłane przy zerowej prędkości.
Most zapamiętuje je jako cel i dosyła po starcie.

**Potwierdzenie startu potrafi przyjść po 7 sekundach.** Limit 5 s robił z udanej komendy
błąd i przerywał dosyłanie celów; teraz limit to 10 s, a brak potwierdzenia i tak nie
przerywa dosyłania — status maszyny (`0x2ada`) pokazuje `04`, gdy taśma rusza, `02 01`
i `02 02` przy zatrzymaniu.

## Rozgłaszanie: bieżnia śpi

Bieżnia rozgłasza się tylko przez krótką chwilę po włączeniu zasilania. Potem milknie
i nie da się jej znaleźć ani po adresie, ani skanem — jedyne wyjście to pstryknąć
wyłącznikiem. Dlatego most nie odpytuje co jakiś czas, tylko **skanuje bez przerwy**
i bierze urządzenie w momencie, gdy się odezwie.

Telefon z appką Urevo wygrywa ten wyścig: gdy się połączy, bieżnia przestaje się
rozgłaszać dla kogokolwiek innego. Na czas pracy z pluginem Bluetooth w telefonie
musi być wyłączony.
