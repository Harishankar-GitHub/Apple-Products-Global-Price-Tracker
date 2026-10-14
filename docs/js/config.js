// Where the API lives. A page opened from this computer (http://localhost or
// 127.0.0.1, while developing) talks to the API running here (python app.py in
// api/); anywhere else, such as GitHub Pages, it talks to the live API.
export const LIVE_API = "https://apple-products-global-price-tracker.onrender.com";
export const LOCAL_API = "http://localhost:5000";

const THIS_COMPUTER = ["localhost", "127.0.0.1", "[::1]"];

export const API_BASE = THIS_COMPUTER.includes(location.hostname) ? LOCAL_API : LIVE_API;
