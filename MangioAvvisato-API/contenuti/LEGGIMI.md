# Contenuti curati a mano

I file di questa cartella si modificano direttamente da GitHub (matita, poi
*Commit changes*). Ogni modifica avvia il workflow, che pubblica i contenuti
in pochi minuti senza contattare il portale del Ministero.

## news.json – avvisi di servizio

Un elenco di notizie. L'app le mostra dalla più recente e notifica quelle nuove.

```json
[
  {
    "id": "manutenzione-novembre",
    "data": "2026-11-05",
    "titolo": "Dati in ritardo",
    "testo": "Il portale del Ministero è irraggiungibile: i richiami arriveranno appena torna disponibile.",
    "link": "https://www.salute.gov.it/"
  }
]
```

- `id`: un nome unico e stabile (lettere, numeri, trattini). Non cambiarlo
  dopo la pubblicazione, altrimenti l'app la considera una notizia nuova.
- `data`: in formato AAAA-MM-GG.
- `link`: facoltativo.

Attenzione alle virgole tra una notizia e l'altra e alle virgolette: se il
file non è un JSON valido, l'app riceve un elenco vuoto. Puoi controllarlo
incollandolo su un validatore JSON prima del commit.

## approfondimenti.json – "Di cosa si tratta?"

Le schede che l'app apre dal dettaglio di un richiamo. Per ogni richiamo
l'app usa la prima scheda le cui `parole` compaiono nel motivo o nel testo
del modello di richiamo; se nessuna corrisponde, quella della sua categoria
di rischio (`categorie`: microbiologico, allergeni, chimico, fisico, altro).
