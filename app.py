
import io
import time
import uuid
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st
from cryptography.fernet import Fernet
from supabase import create_client


# --------------------------------------------------
# PAGE CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="Distributed Cloud File Transfer Accelerator",
    page_icon="☁️",
    layout="wide",
)

st.title("☁️ Distributed Cloud File Transfer Accelerator")
st.write(
    "A cloud-based file transfer system that encrypts files, "
    "splits them into blocks, and uses parallel downloads "
    "to compare transfer performance."
)

st.info(
    "This application uses Supabase cloud storage, "
    "Fernet encryption, and Python concurrent processing."
)


# --------------------------------------------------
# CONNECT TO SUPABASE
# --------------------------------------------------

@st.cache_resource
def get_supabase_client():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


try:
    supabase = get_supabase_client()
except Exception as error:
    st.error(
        "Could not connect to Supabase. Check your "
        ".streamlit/secrets.toml configuration."
    )
    st.caption(f"Technical details: {error}")
    st.stop()


BUCKET_NAME = "file-blocks"


# --------------------------------------------------
# PROJECT OVERVIEW
# --------------------------------------------------

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### ☁️ Cloud Storage")
    st.write("Store encrypted file blocks in a private Supabase bucket.")

with col2:
    st.markdown("### ⚡ Parallel Downloads")
    st.write("Download multiple blocks concurrently.")

with col3:
    st.markdown("### 🔐 Encryption")
    st.write("Encrypt each block before uploading it.")


# --------------------------------------------------
# FILE INPUT AND SETTINGS
# --------------------------------------------------

st.divider()
st.subheader("1. Select a file")

uploaded_file = st.file_uploader(
    "Choose a file to transfer",
    type=None,
)

block_size_mb = st.select_slider(
    "Block size",
    options=[1, 2, 4, 8],
    value=1,
    help="Smaller blocks create more cloud objects.",
)

workers = st.slider(
    "Parallel download workers",
    min_value=2,
    max_value=8,
    value=4,
    help="Number of downloads allowed to run concurrently.",
)

if uploaded_file is not None:
    file_bytes = uploaded_file.getvalue()

    st.write(f"**File:** {uploaded_file.name}")
    st.write(f"**Size:** {len(file_bytes):,} bytes")

    if len(file_bytes) == 0:
        st.warning("Please select a non-empty file.")

    elif len(file_bytes) > 20 * 1024 * 1024:
        st.error(
            "For this demonstration, choose a file smaller "
            "than or equal to 20 MB."
        )

    elif st.button("🚀 Start Cloud Transfer", type="primary"):

        if not st.secrets.get("SUPABASE_URL") or not st.secrets.get("SUPABASE_KEY"):
            st.error("Supabase credentials are missing.")
            st.stop()

        run_id = str(uuid.uuid4())
        encryption_key = Fernet.generate_key()
        cipher = Fernet(encryption_key)

        chunk_size = block_size_mb * 1024 * 1024
        blocks = [
            file_bytes[i:i + chunk_size]
            for i in range(0, len(file_bytes), chunk_size)
        ]

        uploaded_paths = []
        encrypted_blocks = []

        st.divider()
        st.subheader("2. Encrypt and upload blocks")

        progress = st.progress(0)
        status = st.empty()

        try:
            upload_start = time.perf_counter()

            for index, block in enumerate(blocks):
                encrypted_block = cipher.encrypt(block)

                # Unique object paths prevent filename collisions.
                object_path = f"{run_id}/{index:05d}.bin"

                supabase.storage.from_(BUCKET_NAME).upload(
                    object_path,
                    encrypted_block,
                    file_options={
                        "content-type": "application/octet-stream",
                        "upsert": "false",
                    },
                )

                uploaded_paths.append(object_path)
                encrypted_blocks.append(encrypted_block)

                progress.progress((index + 1) / len(blocks))
                status.write(
                    f"Uploaded encrypted block {index + 1} "
                    f"of {len(blocks)}"
                )

            upload_time = time.perf_counter() - upload_start

        except Exception as error:
            st.error(f"Cloud upload failed: {error}")
            st.stop()

        st.success(f"Uploaded {len(blocks)} encrypted blocks.")
        st.write(f"**Upload time:** {upload_time:.3f} seconds")

        # Keep the generated key available in this session.
        st.session_state["last_encryption_key"] = encryption_key.decode()
        st.session_state["last_file_name"] = uploaded_file.name

        st.download_button(
            "🔑 Download encryption key (keep it private)",
            data=encryption_key,
            file_name="file_encryption_key.key",
            mime="application/octet-stream",
            help="Save this key securely. It is not stored in the database.",
        )

        # --------------------------------------------------
        # SEQUENTIAL DOWNLOAD
        # --------------------------------------------------

        st.divider()
        st.subheader("3. Compare download performance")

        sequential_data = []
        sequential_start = time.perf_counter()

        try:
            for path in uploaded_paths:
                result = supabase.storage.from_(BUCKET_NAME).download(path)
                sequential_data.append(result)

            sequential_time = time.perf_counter() - sequential_start

        except Exception as error:
            st.error(f"Sequential download failed: {error}")
            st.stop()

        st.write(
            f"**Sequential download:** {sequential_time:.3f} seconds"
        )

        # --------------------------------------------------
        # PARALLEL DOWNLOAD
        # --------------------------------------------------

        parallel_data = [None] * len(uploaded_paths)
        parallel_start = time.perf_counter()

        def download_block(item):
            index, path = item
            result = supabase.storage.from_(BUCKET_NAME).download(path)
            return index, result

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(download_block, item)
                    for item in enumerate(uploaded_paths)
                ]

                for future in as_completed(futures):
                    index, result = future.result()
                    parallel_data[index] = result

            parallel_time = time.perf_counter() - parallel_start

        except Exception as error:
            st.error(f"Parallel download failed: {error}")
            st.stop()

        st.write(
            f"**Parallel download ({workers} workers):** "
            f"{parallel_time:.3f} seconds"
        )

        # --------------------------------------------------
        # DECRYPT AND REASSEMBLE
        # --------------------------------------------------

        st.divider()
        st.subheader("4. Decrypt and reconstruct file")

        try:
            decrypted_blocks = [
                cipher.decrypt(block)
                for block in parallel_data
            ]

            reconstructed_file = b"".join(decrypted_blocks)

        except Exception as error:
            st.error(f"Decryption or reconstruction failed: {error}")
            st.stop()

        original_hash = hashlib.sha256(file_bytes).hexdigest()
        recovered_hash = hashlib.sha256(reconstructed_file).hexdigest()
        integrity_verified = original_hash == recovered_hash

        if integrity_verified:
            st.success(
                "File reconstructed successfully! "
                "SHA-256 verification confirms the recovered file "
                "matches the original."
            )
        else:
            st.error(
                "Integrity verification failed. The recovered file "
                "does not match the original."
            )

        st.download_button(
            "⬇️ Download reconstructed file",
            data=reconstructed_file,
            file_name=uploaded_file.name,
            mime="application/octet-stream",
        )

        # --------------------------------------------------
        # PERFORMANCE METRICS
        # --------------------------------------------------

        st.divider()
        st.subheader("5. Performance analysis")

        metric1, metric2, metric3 = st.columns(3)

        metric1.metric(
            "File blocks",
            len(blocks),
        )

        metric2.metric(
            "Sequential download",
            f"{sequential_time:.3f} s",
        )

        metric3.metric(
            "Parallel download",
            f"{parallel_time:.3f} s",
        )

        if parallel_time > 0:
            speedup = sequential_time / parallel_time
            st.metric("Parallel speedup", f"{speedup:.2f}×")

            if parallel_time < sequential_time:
                improvement = (
                    (sequential_time - parallel_time)
                    / sequential_time
                ) * 100

                st.write(
                    f"Parallel downloads were approximately "
                    f"{improvement:.1f}% faster in this run."
                )
            else:
                st.write(
                    "Parallel downloads were not faster in this run. "
                    "Network conditions, file size, and cloud latency "
                    "can affect the results."
                )

        st.caption(
            "Timings are measured separately. Results vary with network "
            "conditions, cloud response times, block size, and worker count."
        )

        # --------------------------------------------------
        # SAVE TRANSFER HISTORY
        # --------------------------------------------------

        try:
            supabase.table("transfer_history").insert(
                {
                    "file_name": uploaded_file.name,
                    "original_size": len(file_bytes),
                    "block_count": len(blocks),
                    "sequential_time": sequential_time,
                    "parallel_time": parallel_time,
                    "encryption_enabled": True,
                }
            ).execute()

            st.success("Transfer statistics saved to the database.")

        except Exception as error:
            st.warning(
                "The file transfer succeeded, but transfer history "
                f"could not be saved: {error}"
            )

        st.write("**Integrity check:**", "PASS" if integrity_verified else "FAIL")

else:
    st.caption(
        "Select a file above to test encryption, cloud storage, "
        "sequential downloads, parallel downloads, and file recovery."
    )

st.divider()
st.caption(
    "Academic demonstration project | Python • Streamlit • Supabase • "
    "Fernet • Concurrent Downloads"
)