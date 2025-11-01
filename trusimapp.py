import os
import sys
import time
from datetime import datetime
from typing import List, Dict, Any
import re

import streamlit as st
import pandas as pd

# Try to import chatbot backend from RAG folder
_RAG_DIR = os.path.join(os.path.dirname(__file__), "RAG")
if os.path.isdir(_RAG_DIR) and _RAG_DIR not in sys.path:
    sys.path.append(_RAG_DIR)
try:
    from prem_rag import getPremAnswer  # type: ignore
except Exception:  # graceful fallback if RAG not present
    getPremAnswer = None  # type: ignore


# ---------- App Config ----------
st.set_page_config(page_title="TurismApp", page_icon="🧭", layout="wide")


# ---------- Static Data (mirrors original HTML) ----------
PLACES: List[Dict[str, Any]] = [
    {
        "id": 1,
        "name": "La casa de la Cultura",
        "category": "monument",
        "rating": 4.8,
        "reviews": 1240,
        "distance": "0.5 km",
        "description": "Hermosa catedral colonial del siglo XVI con arquitectura impresionante",
        "price": "Gratis",
        "image": os.path.join("images V1", "casacultura.jpg"),
        "coordinates": [10.4236, -75.5378],
        "openHours": "6:00 AM - 7:00 PM",
        "features": ["Guía disponible", "Acceso para discapacitados", "Fotografía permitida"],
    },
    {
        "id": 2,
        "name": "Juan Hotel",
        "category": "restaurant",
        "rating": 4.6,
        "reviews": 890,
        "distance": "0.8 km",
        "description": "Auténtica comida caribeña con los mejores ceviches de la ciudad",
        "price": "$$",
        "image": os.path.join("images V1", "Mezquita-Omar-IbnAl-hattab-Maicao-768x473.webp"),
        "coordinates": [10.4242, -75.5376],
        "openHours": "11:00 AM - 10:00 PM",
        "features": ["Terraza", "Reservas online", "Menú vegetariano"],
    },
    {
        "id": 3,
        "name": "AL Maiz",
        "category": "hotel",
        "rating": 3.5,
        "reviews": 456,
        "distance": "0.8 km",
        "description": "Hotel boutique en el corazón de la ciudad amurallada",
        "price": "$180/noche",
        "image": os.path.join("images V1", "al_maiz1.jpg"),
        "coordinates": [10.4230, -75.5380],
        "openHours": "24 horas",
        "features": ["Piscina", "Spa", "Desayuno incluido", "WiFi gratis"],
    },
    {
        "id": 4,
        "name": "Tour Islas del Rosario",
        "category": "activity",
        "rating": 4.7,
        "reviews": 2100,
        "distance": "15 km",
        "description": "Excursión de día completo a las paradisíacas islas del Rosario",
        "price": "$241.000 COP/persona",
        "image": os.path.join("images V1", "Reserva-Natural-Los-Flamencos-Maicao.webp"),
        "coordinates": [10.1733, -75.7667],
        "openHours": "8:00 AM - 5:00 PM",
        "features": ["Transporte incluido", "Almuerzo", "Snorkel", "Guía bilingüe"],
    },
]


# ---------- Helpers ----------
def get_place(place_id: int) -> Dict[str, Any]:
    return next((p for p in PLACES if p["id"] == place_id), {})


def ensure_state():
    if "search_query" not in st.session_state:
        st.session_state.search_query = ""
    if "selected_category" not in st.session_state:
        st.session_state.selected_category = "all"
    if "favorites" not in st.session_state:
        st.session_state.favorites = set()
    if "itinerary" not in st.session_state:
        st.session_state.itinerary = []  # list of place dicts with time
    if "is_offline" not in st.session_state:
        st.session_state.is_offline = False
    if "selected_place_id" not in st.session_state:
        st.session_state.selected_place_id = None
    if "show_chat" not in st.session_state:
        st.session_state.show_chat = False
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "¿Cómo te puedo ayudar hoy?"}
        ]
    if "chat_temperature" not in st.session_state:
        st.session_state.chat_temperature = 0.1
    if "chat_top_p" not in st.session_state:
        st.session_state.chat_top_p = 0.9
    if "chat_max_length" not in st.session_state:
        st.session_state.chat_max_length = 512
    if "exchange_rate_usd_cop" not in st.session_state:
        # Tasa por defecto; el usuario puede ajustarla en la UI
        st.session_state.exchange_rate_usd_cop = 4200.0


def format_cop(value: float) -> str:
    # Formatea con separador de miles como en Colombia (puntos)
    return ("{:,.0f}".format(value)).replace(",", ".")


def convert_price_to_cop(price_text: str, exchange_rate_usd_cop: float) -> str:
    """Convierte precios con símbolo $ (asumidos USD) a COP, conservando sufijos.
    - Si ya contiene 'COP' o dice 'Gratis'/'$$', lo deja igual.
    - Detecta montos como $180, $65.50, etc., y añade sufijos como '/noche'.
    """
    if not isinstance(price_text, str):
        return price_text
    normalized = price_text.strip()
    if not normalized:
        return price_text
    # No tocar si ya está en COP o si es Gratis o símbolos no cuantitativos
    if "COP" in normalized.upper() or "GRATIS" in normalized.upper() or normalized in {"$", "$$", "$$$"}:
        return normalized
    # Buscar patrón $<numero> opcionalmente con decimales, y capturar sufijo
    m = re.match(r"^\$(\d+(?:[\.,]\d+)?)\s*(.*)$", normalized)
    if not m:
        return normalized
    amount_str, suffix = m.groups()
    amount_str = amount_str.replace(".", "").replace(",", ".")
    try:
        usd_value = float(amount_str)
    except ValueError:
        return normalized
    cop_value = usd_value * float(exchange_rate_usd_cop)
    cop_formatted = format_cop(cop_value)
    suffix = suffix.strip()
    suffix_part = f" {suffix}" if suffix else ""
    return f"${cop_formatted} COP{suffix_part}"


def filter_places() -> List[Dict[str, Any]]:
    q = st.session_state.search_query.lower().strip()
    category = st.session_state.selected_category
    results = []
    for place in PLACES:
        matches_search = q in place["name"].lower() or q in place["description"].lower()
        matches_category = category == "all" or place["category"] == category
        if matches_search and matches_category:
            results.append(place)
    return results


def toggle_favorite(place_id: int):
    favs = st.session_state.favorites
    if place_id in favs:
        favs.remove(place_id)
    else:
        favs.add(place_id)


def add_to_itinerary(place_id: int):
    place = get_place(place_id)
    if place and not any(item["id"] == place_id for item in st.session_state.itinerary):
        entry = dict(place)
        entry["time"] = datetime.now().strftime("%I:%M %p")
        st.session_state.itinerary.append(entry)


def render_place_card(place: Dict[str, Any], compact: bool = False, key_prefix: str = "card"):
    with st.container(border=True):
        if compact:
            cols = st.columns([1, 3, 2])
        else:
            cols = st.columns([1, 2, 2])

        # Image
        with cols[0]:
            if os.path.exists(place["image"]):
                st.image(place["image"], use_container_width=True)
            else:
                st.markdown(f"Imagen no encontrada: `{place['image']}`")

        # Info
        with cols[1]:
            st.subheader(place["name"])  # title
            st.markdown(
                f"⭐ **{place['rating']}** ({place['reviews']} reseñas) · 📍 {place['distance']}"
            )
            st.caption(place["description"]) 
            converted_price = convert_price_to_cop(str(place['price']), st.session_state.exchange_rate_usd_cop)
            st.markdown(
                f"**{converted_price}** · 🕒 {place['openHours']}"
            )

        # Actions
        with cols[2]:
            heart_label = "❤️ Quitar de favoritos" if place["id"] in st.session_state.favorites else "🤍 Añadir a favoritos"
            if st.button(heart_label, key=f"{key_prefix}_fav_{place['id']}"):
                toggle_favorite(place["id"]) 
                st.rerun()

            if st.button("Ver más", key=f"{key_prefix}_ver_{place['id']}"):
                st.session_state.selected_place_id = place["id"]
                st.rerun()

            if st.button("+ Itinerario", key=f"{key_prefix}_itin_{place['id']}"):
                add_to_itinerary(place["id"]) 
                st.toast("¡Lugar añadido al itinerario!", icon="✅")


def render_place_detail_modal():
    place_id = st.session_state.selected_place_id
    if not place_id:
        return
    place = get_place(place_id)
    if not place:
        return

    # Best-effort modal: sidebar to emulate modal behavior for broad compatibility
    with st.sidebar:
        st.markdown("---")
        st.header(place["name"])
        if os.path.exists(place["image"]):
            st.image(place["image"], use_container_width=True)
        converted_price = convert_price_to_cop(str(place['price']), st.session_state.exchange_rate_usd_cop)
        st.markdown(
            f"⭐ {place['rating']} ({place['reviews']} reseñas)\n\n"
            f"📍 {place['distance']}\n\n"
            f"🕒 {place['openHours']}\n\n"
            f"💳 **{converted_price}**"
        )

        st.subheader("Características")
        for feature in place.get("features", []):
            st.markdown(f"- {feature}")

        st.subheader("Descripción")
        st.write(place["description"]) 

        cols = st.columns(2)
        with cols[0]:
            if st.button("Reservar ahora", key=f"reserva_{place_id}"):
                st.info("Funcionalidad de reserva en desarrollo. ¡Pronto disponible!")
        with cols[1]:
            if st.button("Añadir a itinerario", key=f"add_it_{place_id}"):
                add_to_itinerary(place_id)
                st.toast("Añadido al itinerario", icon="🗓️")

        if st.button("Cerrar", key=f"cerrar_{place_id}"):
            st.session_state.selected_place_id = None
            st.rerun()


def render_header():
    left, right = st.columns([3, 2])
    with left:
        top_cols = st.columns([1, 6])
        with top_cols[0]:
            logo_path = "logo.PNG" if os.path.exists("logo.PNG") else None
            if logo_path:
                st.image(logo_path, width=56)
        with top_cols[1]:
            st.title("ECOguajira aventuras")
    with right:
        st.write("")
        st.write("")
        status_col1, status_col2 = st.columns([1, 1])
        with status_col1:
            status_label = "🔴 Offline" if st.session_state.is_offline else "🟢 Online"
            st.metric(label="Estado", value=status_label)
        with status_col2:
            st.session_state.is_offline = st.toggle(
                "Modo Offline", value=st.session_state.is_offline, help="Simular modo sin conexión"
            )
        # Control de tasa de cambio USD->COP
        rate_col = st.columns(1)[0]
        st.session_state.exchange_rate_usd_cop = rate_col.number_input(
            "Tasa USD→COP",
            min_value=1000.0,
            max_value=20000.0,
            value=float(st.session_state.exchange_rate_usd_cop),
            step=50.0,
            help="Tasa usada para convertir precios en USD a COP",
        )
        # Chatbot toggle button
        chat_col = st.columns(1)[0]
        if chat_col.button("💬 Chatbot", key="open_chat_btn"):
            st.session_state.show_chat = not st.session_state.show_chat
            st.rerun()


def render_explore_tab():
    banner_path = os.path.join("images", "explorar.jpg")
    if os.path.exists(banner_path):
        st.image(banner_path, use_container_width=True)

    st.markdown("### Buscar")
    s_col1, s_col2, s_col3 = st.columns([6, 1, 1])
    with s_col1:
        st.session_state.search_query = st.text_input(
            "Buscar lugares, restaurantes, hoteles...", value=st.session_state.search_query, label_visibility="collapsed"
        )
    with s_col2:
        if st.button("🔍", use_container_width=True):
            pass  # typing triggers filtering automatically
    with s_col3:
        st.button("📊", use_container_width=True, disabled=True)

    st.markdown("### Categorías")
    options_list = [
        ("all", "🌎 Todo"),
        ("monument", "🏛️ Monumentos"),
        ("restaurant", "🍽️ Restaurantes"),
        ("hotel", "🏨 Hoteles"),
        ("activity", "🎯 Actividades"),
        ("shopping", "🛍️ Compras"),
        ("events", "🎪 Eventos"),
    ]
    labels = [label for _, label in options_list]
    keys = [key for key, _ in options_list]
    default_index = keys.index(st.session_state.selected_category) if st.session_state.selected_category in keys else 0
    selected_label = st.radio(
        "",
        options=labels,
        index=default_index,
        horizontal=True,
        key="cat_selector_radio",
    )
    # map back to key
    selected_idx = labels.index(selected_label)
    st.session_state.selected_category = keys[selected_idx]

    st.markdown("---")
    for place in filter_places():
        render_place_card(place, key_prefix="explore")


def render_map_tab():
    st.markdown("### Mapa Interactivo")
    c1, c2 = st.columns([6, 1])
    with c2:
        st.metric(label="Señal", value="📶")

    # Interactive map using Streamlit built-in map (fallback) without external keys
    data = [{"lat": p["coordinates"][0], "lon": p["coordinates"][1], "name": p["name"], "id": p["id"], "category": p["category"]} for p in PLACES]
    if data:
        df = pd.DataFrame(data)
        st.map(df[["lat", "lon"]], size=120)
        sel = st.selectbox("Ver detalles de:", df["name"].tolist(), index=0)
        pid = df.loc[df["name"] == sel, "id"].iloc[0]
        if st.button("Abrir detalle", key="map_open_detail"):
            st.session_state.selected_place_id = int(pid)
            st.rerun()
    else:
        st.info("Sin puntos para mostrar en el mapa.")


def render_chatbot_panel():
    if not st.session_state.show_chat:
        return

    with st.container(border=True):
        st.subheader("Asistente - Chatbot")

        with st.expander("Parámetros del modelo", expanded=False):
            st.session_state.chat_temperature = st.slider(
                "Temperatura", min_value=0.01, max_value=1.0, value=float(st.session_state.chat_temperature), step=0.01, key="chat_temp_slider"
            )
            st.session_state.chat_top_p = st.slider(
                "Top p", min_value=0.01, max_value=1.0, value=float(st.session_state.chat_top_p), step=0.01, key="chat_top_p_slider"
            )
            st.session_state.chat_max_length = st.slider(
                "Longitud máxima", min_value=64, max_value=4096, value=int(st.session_state.chat_max_length), step=8, key="chat_max_len_slider"
            )

        def clear_chat_history():
            st.session_state.messages = [
                {"role": "developer", "content": "Eres un asistente útil para unos estudiantes de colegio en Colombia."},
                {"role": "assistant", "content": "¿Cómo te puedo ayudar hoy?"},
            ]

        clear_cols = st.columns([1, 5])
        with clear_cols[0]:
            st.button("Limpiar historial", on_click=clear_chat_history, key="clear_history_btn")

        # Show existing messages
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])

        # Input
        prompt = st.chat_input("Escribe tu mensaje...")
        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)

        # Generate response using existing RAG function if available
        if st.session_state.messages and st.session_state.messages[-1]["role"] != "assistant":
            with st.chat_message("assistant"):
                with st.spinner("Pensando..."):
                    time.sleep(0.2)
                    response_text = "Lo siento, el backend del chatbot no está disponible."
                    if getPremAnswer is not None:
                        try:
                            # Pasamos parámetros del panel al backend
                            result = getPremAnswer(
                                prompt,
                                max_tokens=int(st.session_state.chat_max_length),
                                model_name="gpt-4o-mini",
                                temperature=float(st.session_state.chat_temperature),
                                top_p=float(st.session_state.chat_top_p),
                            )
                            response_text = getattr(result, "content", result)
                        except Exception as e:
                            response_text = f"Error del chatbot: {e}"

                    # Typewriter effect
                    placeholder = st.empty()
                    full_response = ""
                    for ch in str(response_text):
                        full_response += ch
                        placeholder.markdown(full_response)
                    placeholder.markdown(full_response)

            st.session_state.messages.append({"role": "assistant", "content": full_response})


def render_itinerary_tab():
    st.markdown("### Mi Itinerario")
    if not st.session_state.itinerary:
        st.info("Tu itinerario está vacío. Añade lugares desde la pestaña Explorar.")
        return

    for item in st.session_state.itinerary:
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.subheader(item["name"])
                st.caption(item["description"]) 
                st.markdown(f"📍 {item['distance']} · {item['price']}")
            with right:
                st.write("")
                st.write("")
                st.text(item.get("time", ""))

    st.markdown("---")
    if st.button("Optimizar ruta"):
        st.toast("Optimizando ruta... ¡Ruta optimizada!", icon="🗺️")


def render_favorites_tab():
    st.markdown("### Mis Favoritos")
    fav_ids = list(st.session_state.favorites)
    if not fav_ids:
        st.info("No tienes favoritos aún. Marca lugares como favoritos para verlos aquí.")
        return

    fav_places = [p for p in PLACES if p["id"] in fav_ids]
    for p in fav_places:
        render_place_card(p, compact=True, key_prefix="favorites")


def render_fab():
    st.markdown(
        """
        <style>
        .fab-btn {position: fixed; bottom: 24px; right: 24px; z-index: 9999;}
        </style>
        <div class="fab-btn">
            <form action="#" method="get">
                <button type="submit">🧭</button>
            </form>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main():
    ensure_state()
    render_header()

    # Tabs
    tab_labels = ["Explorar", "Mapa", "Itinerario", "Favoritos"]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        render_explore_tab()
    with tabs[1]:
        render_map_tab()
    with tabs[2]:
        render_itinerary_tab()
    with tabs[3]:
        render_favorites_tab()

    # Detail view (acts like a modal in the sidebar)
    render_place_detail_modal()

    # Floating action button
    render_fab()

    # Chatbot (toggle panel)
    render_chatbot_panel()


if __name__ == "__main__":
    main()


