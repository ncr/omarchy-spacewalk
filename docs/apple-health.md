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

Wszystko leży w `~/.local/state/omarchy-treadmill/sessions.jsonl`, po jednej linii na
przejście, z flagą `sent`.

## Skrót na iPhonie

Nazwa `spawner` poniżej to nazwa komputera w tailnecie (MagicDNS). Gdyby nie działała,
wpisz adres: `http://100.90.167.96:8787`.

1. **Pobierz zawartość URL** — `http://spawner:8787/pending`
2. **Pobierz wartość słownika** — klucz `sessions`, ze Zawartości URL
3. **Powtórz dla każdego** — z wyniku kroku 2, a w środku:
   - **Pobierz wartość słownika** `steps` → **Zapisz próbkę zdrowia**: typ *Kroki*,
     wartość ta liczba, data = wartość klucza `end`
   - **Pobierz wartość słownika** `distance_m` → **Zapisz próbkę zdrowia**:
     typ *Dystans marszu i biegu*, jednostka metry
   - **Pobierz wartość słownika** `kcal` → **Zapisz próbkę zdrowia**:
     typ *Aktywna energia*, jednostka kcal
4. Po pętli: **Pobierz zawartość URL** — `http://spawner:8787/ack-all`

Typu w akcji „Zapisz próbkę zdrowia" nie da się podać zmienną — stąd trzy osobne akcje.

## Kiedy to uruchamiać

W Skrótach → Automatyzacja. Wyzwalacz czasowy (np. 21:00) albo „gdy iPhone łączy się
z ładowarką". Od iOS 16.4 automatyzacje osobiste mogą chodzić bez pytania o zgodę —
w ustawieniach automatyzacji wyłącz „Pytaj przed uruchomieniem".

Telefon musi mieć włączony Tailscale i widzieć komputer; komputer musi być włączony.
Nieodebrane przejścia czekają w kolejce, więc uruchomienie po kilku dniach wyśle
wszystkie zaległe.

## Podwójne liczenie

Kroki z bieżni dopisują się do tego, co Zdrowie ma z innych źródeł. Przy chodzeniu
z telefonem na biurku nie ma się co dublować. Gdybyś zaczął chodzić z iPhonem w kieszeni
albo z Apple Watch — wyrzuć ze skrótu akcję z krokami, bo policzą się dwa razy.
