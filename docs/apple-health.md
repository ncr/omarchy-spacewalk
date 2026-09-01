# Wysyłanie przejść do Apple Health

Apple Health nie ma publicznego API do zapisu z zewnątrz — jedyna droga bez płatnych
aplikacji prowadzi przez **Skróty** na iPhonie i ich akcję „Zapisz próbkę zdrowia".
Skrót pobiera przejścia z komputera po Tailscale, zapisuje je do Zdrowia i potwierdza
odbiór, żeby to samo nie trafiło tam dwa razy.

Trening jako całości (Workout) Skróty zapisać nie potrafią — idą trzy osobne próbki:
kroki, dystans i aktywna energia. Na prawdziwy wpis treningowy trzeba płatnej aplikacji
importującej plik `.fit`/`.tcx` (RunGap, HealthFit).

## Co wystawia komputer

Most stawia serwer na **adresie z Tailscale** (nie na localhost, nie w sieci lokalnej),
domyślnie port 8787. Sprawdzenie z komputera:

```bash
curl http://$(tailscale ip -4):8787/pending
```

| Adres | Co robi |
|---|---|
| `GET /pending` | przejścia, których telefon jeszcze nie wziął |
| `GET /ack-all` | oznacza jako wysłane to, co wydało ostatnie `/pending` |
| `GET /ack?ids=a,b` | oznacza wskazane przejścia |
| `GET /today` | sumy dnia, do podglądu |

Przejście zamyka się po 90 sekundach bez ruchu albo przy rozłączeniu z bieżnią.
Przejścia bez ani jednego kroku (taśma kręciła się bez nikogo) nie są zapisywane.

Wszystko leży w `~/.local/state/omarchy-spacewalk/sessions.jsonl`, po jednej linii na
przejście, z flagą `sent`.

## Skrót na iPhonie

Nazwa `spawner` poniżej to nazwa komputera w tailnecie (MagicDNS). Gdyby nie działała,
wpisz adres: `http://100.90.167.96:8787`.

1. **Pobierz zawartość URL** — `http://spawner:8787/pending`
2. **Pobierz wartość dla** `sessions` **w** Zawartość URL
3. **Powtórz dla każdej rzeczy w** Wartość ze słownika. Najpierw wszystkie odczyty
   z nazwanymi zmiennymi, dopiero potem zapisy — inaczej wychodzą zera (dlaczego,
   niżej):
   - **Pobierz wartość dla** `end_text` **w** Powtarzana rzecz
   - **Uzyskaj daty z wejścia** ← zamienia tekst na datę. Bez niej
     „Zarejestruj próbkę zdrowia" dostaje napis zamiast daty i skrót staje.
   - **Ustaw zmienną** `data`
   - **Pobierz wartość dla** `steps` → **Ustaw zmienną** `kroki`
   - **Pobierz wartość dla** `distance_m` → **Ustaw zmienną** `metry`
   - **Pobierz wartość dla** `kcal` → **Ustaw zmienną** `kalorie`
   - **Zarejestruj próbkę zdrowia**: typ *Kroki*, wartość ← `kroki`, data ← `data`
   - **Zarejestruj próbkę zdrowia**: typ *Dystans marszu i biegu*, jednostka *metry*,
     wartość ← `metry`, data ← `data`
   - **Zarejestruj próbkę zdrowia**: typ *Aktywna energia*, jednostka *kcal*,
     wartość ← `kalorie`, data ← `data`
4. Po pętli — **poza nią**, na samym końcu skrótu: **Pobierz zawartość URL**
   → `http://spawner:8787/ack-all`

Dwie rzeczy, na których łatwo się wyłożyć:

- **Wartość w każdej próbce trzeba wstawić jawnie.** Zostawione puste pole bierze wejście
  z poprzedniej akcji, a gdy poprzednia jest zapisem próbki, wejście jest puste → zero.
- **Każde „Pobierz wartość dla" tworzy zmienną o tej samej nazwie**, więc bez nazwanych
  zmiennych łatwo wskazać nie tę, co trzeba.

Dystans wysyłaj w metrach: 30 m w kilometrach to 0,03 i wygląda jak zero.

Typu w akcji „Zarejestruj próbkę zdrowia" nie da się podać zmienną — stąd trzy osobne
akcje. Za pierwszym uruchomieniem iOS zapyta o zgodę na zapis do Zdrowia; bez niej akcja
kończy się błędem.

Każda sesja ma gotowe pola pod Skróty: `end_text` i `start_text` (data ze spacją zamiast
`T`, bo ISO z `T` bywa nieparsowane) oraz `distance_km`, gdyby wygodniej było w kilometrach.

## Gdy skrót nie działa

Sprawdź, czy telefon w ogóle doszedł do komputera — most zapisuje każde żądanie:

```bash
grep '"t":"request"' ~/.local/state/omarchy-spacewalk/bridge.log | tail
```

Wpis z adresem telefonu i `200 OK` przy `/pending` znaczy, że sieć i serwer działają,
a problem jest w samym skrócie. Brak wpisu po `/ack-all` znaczy, że skrót zatrzymał się
w pętli, zanim potwierdził odbiór — najczęściej na dacie albo na braku zgody dla Zdrowia.

## Raz na dobę, samo

W Skrótach → zakładka **Automatyzacja** → **+** → **Pora dnia**: godzina, **Codziennie**,
a na dole **Uruchom natychmiast**. Bez tego ostatniego iOS tylko wyświetla powiadomienie,
które trzeba kliknąć. Dalej → wybierz skrót. „Powiadamiaj o uruchomieniu" można wyłączyć.

Godzinę dobierz pod komputer, bo to z niego lecą dane — jeśli wyłączasz go na noc,
wczesny wieczór jest pewniejszy niż 23:00.

Nieudana próba niczego nie psuje: przejścia zostają w kolejce, dopóki skrót ich nie
potwierdzi, więc następne uruchomienie zabierze także zaległe. Dlatego warto dodać drugą
automatyzację jako zapas — na przykład „gdy iPhone podłączony do ładowarki".

Telefon musi mieć włączony Tailscale i **ważny klucz węzła**: gdy klucz wygasa, urządzenie
nadal widnieje na liście, ale ruch nie przechodzi i skrót kończy się przeterminowaniem.
Sprawdzenie z komputera: `tailscale ping iphone`. Lekarstwo: zalogować się ponownie
w aplikacji Tailscale, a na stałe — „Disable key expiry" w panelu admina.

## Podwójne liczenie

Kroki z bieżni dopisują się do tego, co Zdrowie ma z innych źródeł. Przy chodzeniu
z telefonem na biurku nie ma się co dublować. Gdybyś zaczął chodzić z iPhonem w kieszeni
albo z Apple Watch — wyrzuć ze skrótu akcję z krokami, bo policzą się dwa razy.
