# Macro Dashboard v3.0 — aamun yhteenveto

Yön yhdeksän vaihetta (P1–P9) ovat valmiit haarassa `v3.0-ui`. **Mitään ei ole julkaistu** — sinä
päätät sen. Loppuportti on vihreä: 116 yksikkötestiä, 150/150 reitti × näyttökoko -savutestiä ilman
yhtään JS-virhettä, 69/69 hyväksymiskriteeriä, ja molemmat kokorajat alittuvat.

## Katso nämä ensin

1. **`#map`** — työkalurivi on yksi rivi. Haku, `Layers ▾`, indikaattorivalitsin ja jakso. Ei enää
   neljää overlay-nappia eikä toista liitoslaatikkoa. 1366 px:n läppärillä kartta alkaa 186 pikselin
   korkeudelta (ennen ~330).
2. **`#area/kommune/101`** — uusi *study row*: kuvaaja ja raahattava minikartta vierekkäin. Vanha
   12-välilehtinen KEY FIGURES -lohko (48 korttia) on poissa. Vaihda indikaattoria sirusta — sivu ei
   rakennu uudelleen, vierityskohta ja kartan zoomaus säilyvät.
3. **`#property?p=55.6545,12.539`** — testikohde on sama study row kiinnitettynä nastaan. Liitä
   Google Maps -linkki laatikkoon, valitse säde (500 m · 1 km · 2 km · 5 km) ja avaa kahdeksan
   osiota. `Layers ▾` toimii myös tällä kartalla.
4. **`#data/national`** ja **`#data/sources`** — Market ja lähdeharmonikka ovat nyt taulukoita
   Data-osion välilehtinä. Jokaisella lähteellä on julkaisija, taulukkotunnus, as of, haettu-päivä ja
   lisenssi.
5. **`Export ▾`** (sivupalkin alaosa) — seitsemän tiedostoa, ja **jokaisella rivillä on oma
   lähteensä**. Kokeile *All area data*: 104 028 riviä, avautuu tanskalaisessa Excelissä
   kaksoisklikkauksella.

Kokeile vielä yksi vanha linkki, esimerkiksi `#table/postnr` tai `#analysis?a=55.6545,12.539&la=Testi`
— ne ohjautuvat uusiin osoitteisiin. Vanhat linkit eivät rikkoutuneet.

## Viisi suurinta muutosta

1. **Yksi indikaattorivalitsin kaikkialla.** Sama painike, sama popover, sama näppäimistömalli
   kartalla, aluesivulla, Data › Areas -taulukossa, Chartsissa ja testikohteessa. Sen valinta ohjaa
   kartan värit, kuvaajan, korostetun sarakkeen ja minikartan — ei enää kahta paikkaa valita sama asia.
2. **Ilmasto on indikaattoriperhe, ei overlay.** *Climate risk* -nappi poistettiin. Kun valitset
   minkä tahansa ilmastoindikaattorin, myrskytulvavyöhykkeet ja viralliset riskialueet piirtyvät
   valitsemallesi horisontille omana kontekstitasonaan, omalla selitteellään ja omalla katkaisijalla.
   Jaksovalitsin vaihtuu samalla vuodesta horisonttiin (`Tänään · 2070 · 2120`).
3. **Neljä kohdetta seitsemän sijaan.** `Map · Data · Charts · Test property`. Market ja Pipeline ovat
   Data-osion välilehtiä, **Compare on poistettu kokonaan** (omistajan päätös A1) ja vanha
   `#compare`-linkki vie ensimmäisen alueen omalle sivulle.
4. **Yksi vientimalli.** Yksi pitkä skeema alueille, kansallisille sarjoille ja testikohteelle;
   projekteilla, lähdeluettelolla ja ilmastoaltistuksella omansa. Jokaisella rivillä `source`,
   `table_id`, `source_url`, `as_of`, `fetched` ja `licence` — ei yhtään tyhjää. v2.6:n kDKK-bugi
   (kDKK-otsikko DKK-luvun päällä) on korjattu vientirajapinnassa.
5. **Responsiivisuus on layout, ei laastari.** Alle 1025 px sivupalkki muuttuu 52 px:n yläpalkiksi ja
   ☰-valikoksi, sivu vierii natiivisti, taulukot vierivät kortin sisällä ensimmäinen sarake
   lukittuna. **Mikään ei enää vieritä sivua vaakasuunnassa** millään neljästä leveydestä — se on nyt
   testivirhe, ei huomautus.

## Mikä jäi tekemättä

**Siirretty myöhemmäksi (omistajan päätös, ei vika):**

- **Portfolio / monta nastaa.** Testikohde näyttää yhden osoitteen kerrallaan (päätös A2). URL-koodekki
  osaa jo listan (`p=a;b` jäsentyy), joten "liitä useita Google Maps -linkkejä ja ne kaikki näkyvät
  kartalla" vaatii vain näkymän joka silmukoi — ei muutosta linkkiformaattiin.
- Kiinnitettävät sirut (`+`-siru ja localStorage), `Columns ▾` Data › Areas -taulukkoon, kansallinen
  sarja Chartsin entiteettinä, alialueiden sparkline-sarake, `/`-pikanäppäin, päakartan koko ruutu.
- `Everything (.zip)` -vienti, study rowin PNG-vienti, tulostustyyli, tallennetut portfoliot.

**Tiedossa olevat puutteet (ei estä julkaisua, lista `docs/v3/QA.md`):**

- BBR-asuntokantaryhmän väriramppi on sinisen sävy, joka on lähellä ilmastoryhmän sinistä. Sävy tulee
  rekisteristä (`config/indicators.json`), jota tämä ajo ei saanut koskea, eivätkä ne ole koskaan
  samassa selitteessä. **Päivätyö.**
- `#publist` ei vielä yhdistä samannimisiä BBR-rivejä lukumäärällä (testikohteen "Public buildings
  within the ring" tekee sen).
- Kaksi datatehtävää on **tuotu näkyviin, ei piilotettu**: KK:n ja BBR:n eri määritelmä "2010+
  valmistuneista asunnoista" (varoitusrivi niillä neljällä Kööpenhaminan kaupunginosalla joissa ero on
  yli 15 pp) ja myrskytulvaindikaattorien kuvausteksti, joka nimeää oletushorisontin omassa
  lauseessaan.
- Kööpenhaminan kaupunginosarekisterissä ei ole ilmastolukuja, joten ilmastoindikaattori `#map/101`:ssä
  vaihtaa postinumeronäkymään, jossa luku on olemassa.
- Saavutettavuustesti on DOM-tarkistus, ei axe-core (kirjastoa ei ole repossa eikä ajo saa asentaa
  mitään). Kannattaa ajaa oikea axe-core päivällä.

**Mikään vaihe ei kaatunut, eikä mitään jäänyt puolitiehen.** Yöllä tehdyt päätökset ovat rivi
kerrallaan tiedostossa `docs/v3/DECISIONS.md`, vaihekohtainen kuvaus tiedostossa
`docs/v3/PROGRESS.md`, ja loppukatselmuksen vikalista tiedostossa `docs/v3/QA.md`.

## Julkaisu — yksi komento

```bash
./overnight.sh release
```

Se yhdistää `v3.0-ui` → `main`, merkitsee tagin `v3.0` ja pushaa; GitHub Pages julkaisee itse.
Tarkista ensin vielä kerran paikallisesti:

```bash
make serve                         # http://localhost:8080
./overnight.sh gate P9             # rakennus + kaikki testit + savutesti + hyväksymiskriteerit + kokorajat
```

> **Huom.** Koneella on toinen projekti (`Macro Dashboard · Sweden`), joka pitää ajoittain porttia
> 8080. Testiajurit tarkistavat sivun otsikon ja tarjoilevat tarvittaessa tämän repon `dist/`-kansion
> itse omasta portistaan — mutta jos avaat `http://localhost:8080/` selaimessa aamulla, **tarkista
> otsikosta että katsot Tanskan dashboardia**.
