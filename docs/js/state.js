// The search on screen: what was asked, what has arrived, and the search still in progress.
// One object, so every module reads and changes the same values.

export const state = {
  allResults:     [],       // every row received for this search, in the order they came
  productName:    "",       // what was typed
  productSlug:    "",       // Apple's identifier for the product that was priced
  shownName:      "",       // product name used in messages (matched name if it differs from what was typed)
  totalCountries: 0,        // rows the API said would come
  receivedCount:  0,
  activeSource:   null,     // the EventSource while the search is running, null once it has ended
  cacheExpiresAt: null,     // Date when cached result expires
  cacheAgeMs:     null,     // how old a cached result is, as reported by the API
  fetchedAt:      null,     // when the prices on screen were fetched from Apple
  serverRates:    null,     // currency → units per 1 USD, sent by the API
  regionFilter:   "all",
};
