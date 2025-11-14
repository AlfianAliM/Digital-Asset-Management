import streamlit as st
import psycopg2
import pandas as pd
import math
import io

# --- PERUBAHAN 1: Import library Google API ---
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
# ---------------------------------------------

# --- Konfigurasi Halaman ---
st.set_page_config(
    page_title="Pencari Konten Gambar",
    page_icon="🖼️",
    layout="wide"
)

# --- PERUBAHAN 1: Fungsi Bantuan untuk GCP/Google Drive ---


# @st.cache_resource
def get_gdrive_credentials():
    """
    Memuat kredensial Service Account dari st.secrets.
    """
    scopes = ['https://www.googleapis.com/auth/drive.readonly']
    try:
        creds_json = st.secrets["gcp_service_account"]
        return Credentials.from_service_account_info(creds_json, scopes=scopes)
    except Exception as e:
        st.error(
            f"Gagal memuat kredensial GCP: Pastikan st.secrets[gcp_service_account] sudah benar. Error: {e}")
        return None


# @st.cache_resource
def get_gdrive_service(_creds):
    """
    Membuat service client Google Drive yang diautentikasi.
    """
    if _creds is None:
        return None
    try:
        return build('drive', 'v3', credentials=_creds)
    except Exception as e:
        st.error(f"Gagal membangun service GDrive: {e}")
        return None


def parse_file_id_from_url(view_url):
    """
    Mengambil FILE_ID dari URL 'view' Google Drive.
    """
    try:
        # Format: .../file/d/{FILE_ID}/view?usp=...
        if "drive.google.com" in view_url and "/d/" in view_url:
            return view_url.split('/d/')[1].split('/')[0]
    except Exception as e:
        print(f"Error parsing GDrive URL '{view_url}': {e}")
        return None
    return None


# @st.cache_data(ttl=3600)  # Cache gambar selama 1 jam
def get_gdrive_file_bytes(_service, file_id):
    """
    Mengunduh file dari Google Drive sebagai bytes.
    """
    if _service is None or file_id is None:
        return None
    try:
        request = _service.files().get_media(fileId=file_id)
        file_buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(file_buffer, request)

        done = False
        while done is False:
            status, done = downloader.next_chunk()
            # print(f"Download {int(status.progress() * 100)}%.") # (Opsional: untuk debug)

        file_buffer.seek(0)
        return file_buffer.getvalue()
    except Exception as e:
        st.error(f"Gagal mengunduh file {file_id}: {e}")
        return None
# ---------------------------------------------------------


# --- Koneksi Database (dengan cache) ---
# @st.cache_resource
def init_connection():
    """
    Inisialisasi koneksi ke database PostgreSQL menggunakan info dari st.secrets.
    """
    try:
        return psycopg2.connect(**st.secrets["postgres"])
    except Exception as e:
        st.error(f"Gagal terhubung ke database: {e}")
        return None


# @st.cache_data(ttl=600)
def fetch_data(_conn):
    """
    Mengambil data dari tabel management_content_img.
    """
    if _conn is None:
        return pd.DataFrame()

    # --- PERUBAHAN: Gunakan 'DISTINCT ON' untuk efisiensi jika ada duplikat link ---
    # Jika 'link' unik, 'SELECT *' saja sudah cukup.
    # Jika mungkin ada duplikat, 'DISTINCT ON (link)' lebih baik.
    # Kita asumsikan 'content_id' (jika ada) adalah unik, atau 'link'
    # 'SELECT DISTINCT *' yang Anda gunakan sudah oke.
    query = "SELECT distinct * FROM management_content_img;"
    try:
        with _conn.cursor() as cur:
            cur.execute(query)
            colnames = [desc[0] for desc in cur.description]
            data = cur.fetchall()
            df = pd.DataFrame(data, columns=colnames)
            return df
    except Exception as e:
        st.error(f"Gagal mengambil data: {e}")
        return pd.DataFrame()

# --- Fungsi Callback untuk Pagination ---


def next_page():
    if st.session_state.current_page < st.session_state.total_pages:
        st.session_state.current_page += 1


def prev_page():
    if st.session_state.current_page > 1:
        st.session_state.current_page -= 1


# --- PERUBAHAN 2: Tambahkan argumen 'key_prefix' ---
def render_pagination_controls(total_items, total_pages, key_prefix=""):
    """
    Menampilkan tombol navigasi halaman dan info halaman.
    Menambahkan 'key_prefix' untuk membuat ID elemen unik.
    """
    if total_items == 0:
        return

    col1, col2, col3 = st.columns([2, 3, 2])

    with col1:
        st.button(
            "⬅️ Sebelumnya",
            on_click=prev_page,
            disabled=(st.session_state.current_page == 1),
            key=f"{key_prefix}_prev"  # Tambahkan key unik
        )

    with col2:
        st.write(
            f"Halaman **{st.session_state.current_page}** dari **{st.session_state.total_pages}**"
        )

    with col3:
        st.button(
            "Selanjutnya ➡️",
            on_click=next_page,
            disabled=(st.session_state.current_page ==
                      st.session_state.total_pages),
            key=f"{key_prefix}_next"  # Tambahkan key unik
        )
# ----------------------------------------------------


# --- Tampilan Utama Aplikasi ---
st.title("🖼️ Pencari Konten Gambar")
st.write("Cari dan filter gambar dari database.")

# Inisialisasi session state untuk pagination
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1

# --- PERUBAHAN 1: Inisialisasi Service GCP ---
creds = get_gdrive_credentials()
gdrive_service = get_gdrive_service(creds)
# ---------------------------------------------

# Coba konek dan ambil data
conn = init_connection()
if conn:
    df = fetch_data(conn)
else:
    st.stop()  # Hentikan eksekusi jika koneksi gagal

if df.empty:
    st.warning("Tidak ada data yang ditemukan di database.")
    st.stop()

# --- Panel Filter ---
# --- Panel Filter ---
st.header("Filter Pencarian", divider="rainbow")
# Bagi layout menjadi 3 kolom
col_filter_1, col_filter_2, col_filter_3 = st.columns(3)

with col_filter_1:
    # Filter Kategori
    categories = ["Semua Kategori"] + sorted(df['category'].unique().tolist())
    selected_category = st.selectbox("Pilih Kategori:", categories)

with col_filter_2:
    # Filter Keyword
    search_term = st.text_input("Cari (judul, deskripsi, atau keyword):")

# --- TAMBAHAN: Filter Klien ---
with col_filter_3:
    # Ambil daftar klien unik, hilangkan NaN/None, lalu urutkan
    client_list = df['klien'].dropna().unique().tolist()
    clients = ["Semua Klien"] + sorted(client_list)
    selected_client = st.selectbox("Pilih Klien:", clients)


# --- Logika Filter Data ---
filtered_df = df.copy()

# 1. Filter berdasarkan Kategori
if selected_category != "Semua Kategori":
    filtered_df = filtered_df[filtered_df['category'] == selected_category]

# --- TAMBAHAN: Filter Klien ---
# 2. Filter berdasarkan Klien
if selected_client != "Semua Klien":
    filtered_df = filtered_df[filtered_df['klien'] == selected_client]

# 3. Filter berdasarkan Search Term (case-insensitive)
if search_term:
    search_term_lower = search_term.lower()
    # Cari di title, description, dan keywords
    mask = (
        filtered_df['title'].str.lower().str.contains(search_term_lower, na=False) |
        filtered_df['description'].str.lower().str.contains(search_term_lower, na=False) |
        filtered_df['keywords'].str.lower().str.contains(
            search_term_lower, na=False)
    )
    filtered_df = filtered_df[mask]

# --- Setup Pagination ---
items_per_page = 10
total_items = len(filtered_df)
total_pages = math.ceil(total_items / items_per_page) if total_items > 0 else 1

st.session_state.total_pages = total_pages

if st.session_state.current_page > total_pages:
    st.session_state.current_page = 1

# --- Menampilkan Hasil ---
st.header(f"Hasil Pencarian ({total_items} ditemukan)", divider="rainbow")

if total_items == 0:
    st.info("Tidak ada hasil yang cocok dengan pencarian Anda.")
else:
    # --- PERUBAHAN 2: Berikan key_prefix 'top' ---
    render_pagination_controls(total_items, total_pages, key_prefix="top")
    st.markdown("---")

    start_index = (st.session_state.current_page - 1) * items_per_page
    end_index = min(start_index + items_per_page, total_items)

    st.write(
        f"Menampilkan item {start_index + 1} - {end_index} dari {total_items} hasil")

    page_df = filtered_df.iloc[start_index:end_index]

    # Loop untuk menampilkan setiap item
    for index, row in page_df.iterrows():
        with st.container(border=True):
            col_img, col_info = st.columns([1, 3])

            with col_img:
                # --- PERUBAHAN 1: Ganti logika thumbnail ke download bytes ---
                file_id = parse_file_id_from_url(row['link'])
                if file_id and gdrive_service:
                    image_bytes = get_gdrive_file_bytes(
                        gdrive_service, file_id)
                    if image_bytes:
                        st.image(image_bytes, width=250)
                    else:
                        st.warning("Gagal memuat gambar (bytes).")
                else:
                    st.warning("URL GDrive tidak valid atau service error.")
                # -----------------------------------------------------------

            with col_info:
                st.subheader(row['title'])
                st.write(row['description'])
                st.caption(f"**Kategori:** {row['category']}")
                st.caption(f"**Keywords:** {row['keywords']}")
                st.link_button("Buka Tautan Asli",
                               row['link'], use_container_width=True)

        st.markdown("---")  # Pemisah antar item

    # --- PERUBAHAN 2: Berikan key_prefix 'bottom' ---
    render_pagination_controls(total_items, total_pages, key_prefix="bottom")
