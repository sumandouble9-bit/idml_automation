import os
import sys
import re
import time
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The table-fitting module lives in the sibling table/ package; add it to the path.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "table"))
try:
    import image_layout_format as fix_image_layout
except ImportError:
    import fix_image_layout
import logo_inject
try:
    import table_fit_format as fix_table_fit
except ImportError:
    import fix_table_fit
import epub_tools
import epub_caption_apply
import injection_scripts as js
from injection_helpers import (
    JS_LANG,
    is_rpc_error,
    clear_recovery_data,
    connect_indesign,
    restart_indesign,
    prepare_image,
    source_sidebyside_pairs,
    pin_document,
    unpin_document,
)

MAX_RETRIES_PER_DOC = 3
PLACEMENT_ATTEMPTS = 3          # tries per image before it counts as failed (transient InDesign hiccups)
PLACEMENT_RETRY_DELAY_S = 0.5


class EpubInjector:
    """Opens each IDML, injects EPUB images/captions, reflows overset, and exports the injected IDML."""

    def __init__(self, input_dir=None, epub_input_dir=None, output_dir=None,
                 output_idml_dir=None, logo_path=None, target_files=None):
        """Resolve input/output/EPUB/logo locations from arguments, environment, and sensible fallbacks."""
        self.here = os.path.dirname(os.path.abspath(__file__))
        self.wf = os.path.dirname(self.here)
        self.repo = self.wf
        self.target_files = target_files

        self.input_dir = self._resolve_input_dir(input_dir)
        print(f"Using IDMLs from input_dir: {self.input_dir}")

        self.epub_input_dir = epub_input_dir or os.environ.get("EPUB_DIR", "").strip() \
            or os.path.join(self.repo, "epub_input_files")
        self.base_image_dir = os.path.join(self.here, "extracted_images")
        self.output_dir = output_dir or os.environ.get("INJECT_OUTBASE", "").strip() \
            or os.path.join(self.wf, "final_output_files")
        self.output_idml_dir = output_idml_dir or os.path.join(self.output_dir, "idml_files")
        self.logo_path = self._resolve_logo_path(logo_path)
        self.log_file = os.path.join(self.output_dir, "batch_injection_log.txt")

        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.output_idml_dir, exist_ok=True)
        os.makedirs(self.base_image_dir, exist_ok=True)

        self.app = None
        self.log_data = []

    def _resolve_input_dir(self, input_dir):
        """Pick the IDML input directory from the argument, $INJECT_INPUT, or the first candidate holding IDMLs."""
        if input_dir is not None:
            return input_dir
        env_input = os.environ.get("INJECT_INPUT", "").strip()
        norm_cands = [
            os.path.join(self.wf, "Output", "page_resize_output"),
            os.path.join(self.wf, "page_resize_output"),
            os.path.join(self.wf, "Output", "Formatted"),
            os.path.join(self.repo, "input_files"),
        ]
        if env_input and os.path.isdir(env_input):
            return env_input
        return next(
            (c for c in norm_cands if os.path.isdir(c) and any(f.lower().endswith(".idml") for f in os.listdir(c))),
            os.path.join(self.repo, "input_files"),
        )

    def _resolve_logo_path(self, logo_path):
        """Pick the logo image from the argument, $LOGO_PATH, or the first known fallback location."""
        if logo_path is None:
            logo_path = os.environ.get("LOGO_PATH", "").strip()
        if not logo_path or not os.path.exists(logo_path):
            for cand in [
                os.path.join(self.repo, "input_files", "logo", "LEAF-BOUND-trimmed.png"),
                os.path.join(self.wf, "logo", "LEAF-BOUND-trimmed.png"),
                os.path.join(self.wf, "logo", "LEAF-BOUND.png"),
            ]:
                if os.path.exists(cand):
                    return cand
        return logo_path

    def _log(self, line):
        """Append one line to the batch log buffer."""
        self.log_data.append(line)

    def _build_file_list(self):
        """Return the IDML filenames to process, honouring target_files and the $INJECT_ONLY filter."""
        if self.target_files:
            idml_files = [os.path.basename(f) for f in self.target_files]
        else:
            idml_files = [f for f in os.listdir(self.input_dir) if f.lower().endswith('.idml')]
        only = os.environ.get("INJECT_ONLY", "").strip()
        if only:
            wanted = {w.strip().lower() for w in only.split(",") if w.strip()}
            idml_files = [f for f in idml_files if f.lower() in wanted]
            print(f"INJECT_ONLY set -> processing {idml_files}")
        return idml_files

    def _split_packed_placeholders(self, keep_pairs=None):
        """Split paragraphs that pack several image placeholders so each image keeps its own caption and order."""
        kl = []
        for pr in (keep_pairs or set()):
            a = sorted(pr)
            if len(a) == 2:
                kl.append('"%s|%s"' % (a[0], a[1]))
        keep_js = "[" + ",".join(kl) + "]"
        return self.app.DoScript(js.split_packed_js(keep_js), JS_LANG)

    def _already_injected(self, idml_path, clean_base, base_name):
        """True when a fresh injected IDML already exists and $INJECT_FORCE is not set."""
        already = os.path.join(self.output_idml_dir, f"{clean_base}_injected.idml")
        if not os.path.exists(already):
            already = os.path.join(self.output_idml_dir, f"{base_name}_injected.idml")
        if os.environ.get("INJECT_FORCE", "0") == "1":
            return False
        return os.path.exists(already) and os.path.getmtime(already) >= os.path.getmtime(idml_path)

    def _extract_epub(self, clean_base, base_name, current_image_folder):
        """Extract the matching EPUB's images and caption data; return (caption_map, caption_styles)."""
        caption_map, caption_styles = {}, {}
        epub_path = os.path.join(self.epub_input_dir, clean_base + ".epub")
        if not os.path.exists(epub_path):
            epub_path = os.path.join(self.epub_input_dir, base_name + ".epub")
        if os.path.exists(epub_path):
            try:
                n_imgs, caption_map, caption_styles = epub_tools.extract_epub(epub_path, current_image_folder)
                print(f"EPUB: extracted {n_imgs} image(s), {len(caption_map)} caption(s) from {os.path.basename(epub_path)}")
                self._log(f"EPUB: {n_imgs} images, {len(caption_map)} captions from {os.path.basename(epub_path)}")
            except Exception as e_epub:
                print(f"EPUB extraction failed for {clean_base}: {e_epub}")
                self._log(f"EPUB extraction failed for {clean_base}: {e_epub}")
        else:
            print(f"WARNING: no EPUB at {epub_path}")
            self._log(f"WARNING: no EPUB for {clean_base}")
        return caption_map, caption_styles

    def _open_document(self, idml_path):
        """Open the IDML in InDesign and return its page count before injection."""
        clean_idml_path = idml_path.replace(chr(92), "/")
        self.app.DoScript(js.open_doc_js(clean_idml_path), JS_LANG)
        self.app = pin_document(self.app)   # later scripts run on THIS document even if another one is activated
        try:
            return int(self.app.DoScript(js.page_count_js(), JS_LANG))
        except Exception:
            return 0

    def _place_with_retry(self, js_name, clean_img_path):
        """Place one image, retrying transient failures; return (placed, reason_when_not_placed)."""
        reason = ""
        for _attempt in range(PLACEMENT_ATTEMPTS):
            try:
                res = self.app.DoScript(js.place_image_js(js_name, clean_img_path), JS_LANG)
                if res == "true":
                    return True, ""
                reason = f"JS: {res[4:]}" if isinstance(res, str) and res.startswith("err:") else "Placeholder Not Found"
            except Exception as e:
                reason = f"Py Error: {str(e).strip()}"
            time.sleep(PLACEMENT_RETRY_DELAY_S)
        return False, reason

    def _inject_images(self, clean_base, current_image_folder, doc_temp_dir):
        """Place each image into its '###Insert ... here###' placeholder; return the failed-image count."""
        src_orig = os.path.join(self.repo, "input_files", f"{clean_base}.idml")
        try:
            keep = source_sidebyside_pairs(src_orig) if os.path.exists(src_orig) else set()
            if keep:
                print(f"Side-by-side pairs kept packed: {sorted(sorted(x) for x in keep)}")
                self._log(f"Side-by-side pairs kept packed: {sorted(sorted(x) for x in keep)}")
            n_split = self._split_packed_placeholders(keep_pairs=keep)
            print(f"Packed paragraphs split: {n_split}")
            self._log(f"Packed paragraphs split: {n_split}")
        except Exception as e_split:
            print(f"Packed split skipped: {e_split}")
            self._log(f"Packed split skipped: {e_split}")

        match_data = self.app.DoScript(js.find_all_placeholders_js(), JS_LANG)
        if not match_data:
            print("No image placeholders found in this document.")
            self._log("Images: 0 placeholders found.")
            return 0

        placeholders = match_data.split("|||")
        total = len(placeholders)
        print(f"Found {total} placeholders. Injecting images...")

        success_count = 0
        fail_count = 0
        failed_images = []

        for i in range(total - 1, -1, -1):
            content = placeholders[i]
            img_name = re.sub(r'[\r\n\t ​]+', ' ', content)
            img_name = img_name.replace("###Insert", "").replace("here###", "").strip()
            img_path = os.path.join(current_image_folder, img_name)
            iteration = total - i

            if not os.path.exists(img_path) and os.path.exists(current_image_folder):
                clean_target = img_name.strip().lower()
                for f_on_disk in os.listdir(current_image_folder):
                    if f_on_disk.strip().lower() == clean_target:
                        img_path = os.path.join(current_image_folder, f_on_disk)
                        img_name = f_on_disk
                        break

            if os.path.exists(img_path):
                final_img_path = prepare_image(img_path, doc_temp_dir)
                js_name = img_name.replace('\\', '\\\\').replace('"', '\\"')
                clean_img_path = final_img_path.replace(chr(92), "/")
                placed, reason = self._place_with_retry(js_name, clean_img_path)
                if placed:
                    success_count += 1
                else:
                    fail_count += 1
                    failed_images.append(f"{img_name} ({reason})")
            else:
                fail_count += 1
                failed_images.append(f"{img_name} (File Not Found in '{current_image_folder}')")

            percent = int(100 * (iteration / float(total)))
            filled = int(30 * iteration // total)
            bar = '#' * filled + '.' * (30 - filled)
            sys.stdout.write(f"\rProgress: [{bar}] {percent}% | Processing: {img_name}".ljust(80))
            sys.stdout.flush()

        print(f"\nImage Injection: {success_count} Injected | {fail_count} Failed")
        self._log(f"Images: {success_count} Injected, {fail_count} Failed")
        if failed_images:
            self._log("Failed Images List:")
            for fi in failed_images:
                self._log(f"  - {fi}")
        return fail_count

    def _run_caption_passes(self, caption_map, caption_styles):
        """Place EPUB captions below images, split merged figure captions, and clean caption artifacts."""
        try:
            caps_applied = epub_caption_apply.apply_captions(self.app, caption_map, caption_styles)
            print(f"EPUB captions placed below images: {caps_applied}")
            self._log(f"EPUB captions placed: {caps_applied}")
        except Exception as e_cap:
            print(f"EPUB caption pass skipped: {e_cap}")
            self._log(f"EPUB caption pass skipped: {e_cap}")

        try:
            caps_split = epub_caption_apply.ensure_split_figure_captions(self.app, caption_map, caption_styles)
            print(f"Split-figure captions inserted: {caps_split}")
            self._log(f"Split-figure captions inserted: {caps_split}")
        except Exception as e_csf:
            print(f"Split-figure caption pass skipped: {e_csf}")
            self._log(f"Split-figure caption pass skipped: {e_csf}")

        try:
            caps_clean = epub_caption_apply.cleanup_caption_artifacts(self.app, caption_map, caption_styles)
            print(f"Caption artifacts cleaned: {caps_clean}")
            self._log(f"Caption artifacts cleaned: {caps_clean}")
        except Exception as e_ccl:
            print(f"Caption cleanup pass skipped: {e_ccl}")
            self._log(f"Caption cleanup pass skipped: {e_ccl}")

    def _run_layout_passes(self):
        """Set inline image leading, normalise NBSP, convert single-cell tables, and enable hyphenation."""
        try:
            inl = self.app.DoScript(js.inline_leading_js(), JS_LANG)
            print(f"Body image inline-leading set: {inl}")
            self._log(f"Body image inline-leading: {inl}")
        except Exception as e_inl:
            print(f"Inline-leading pass skipped: {e_inl}")
            self._log(f"Inline-leading pass skipped: {e_inl}")

        try:
            nbsp_fixed = self.app.DoScript(js.fix_nbsp_js(), JS_LANG)
            print(f"Non-breaking spaces normalized: {nbsp_fixed}")
            self._log(f"Non-breaking spaces normalized: {nbsp_fixed}")
        except Exception as e_nbsp:
            print(f"Non-breaking space normalization skipped: {e_nbsp}")
            self._log(f"NBSP normalization skipped: {e_nbsp}")

        try:
            sc_conv = fix_table_fit.convert_single_cell_tables(self.app)
            print(f"Single-cell tables -> text (pre-reflow): {sc_conv}")
            self._log(f"Single-cell tables -> text (pre-reflow): {sc_conv}")
        except Exception as e_sc:
            print(f"Pre-reflow single-cell conversion skipped: {e_sc}")
            self._log(f"Pre-reflow single-cell conversion skipped: {e_sc}")

        try:
            hy = self.app.DoScript(js.hyphenate_body_js(), JS_LANG)
            print(f"Hyphenation enabled on {hy} paragraph styles")
            self._log(f"Hyphenation enabled: {hy} styles")
        except Exception as e_hy:
            print(f"Hyphenation enable skipped: {e_hy}")
            self._log(f"Hyphenation enable skipped: {e_hy}")

    def _resolve_overset(self, base_name, filename):
        """Add pages for overset body text and write an overset report when content could not be placed."""
        print("Resolving overset text frames dynamically...")
        try:
            reflow_report = self.app.DoScript(js.resolve_overset_js(), JS_LANG)
            report_lines = str(reflow_report).split("\n")
            summary_line = report_lines[0] if report_lines else ""
            jam_lines = [ln for ln in report_lines[1:] if ln.strip()]

            added_str = "0"
            overset_left = "0"
            try:
                parts = dict(p.split("=", 1) for p in summary_line.split("|") if "=" in p)
                added_str = parts.get("PAGES", "0")
                overset_left = parts.get("OVERSET", "0")
            except Exception:
                pass

            print(f"Overset reflow: added {added_str} page(s) | remaining overset frames: {overset_left} | issues flagged: {len(jam_lines)}")
            self._log(f"Overset reflow: added {added_str} page(s), remaining overset frames {overset_left}, issues flagged {len(jam_lines)}")

            if jam_lines:
                report_path = os.path.join(self.output_dir, f"{base_name}_overset_report.txt")
                with open(report_path, "w", encoding="utf-8") as rf:
                    rf.write(f"Overset / oversized-content report for {filename}\n")
                    rf.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    rf.write(f"{summary_line}\n")
                    rf.write("-" * 60 + "\n")
                    rf.write("SHRUNK  = oversized image scaled down to fit the margin-bounded frame (frame never grown).\n")
                    rf.write("UNRESOLVED = non-image element too large to fit; remaining text captured below.\n")
                    rf.write("-" * 60 + "\n\n")
                    for ln in jam_lines:
                        rf.write(ln + "\n\n")
                print(f"  Report written: {report_path}")
                self._log(f"Overset report: {report_path}")
                for ln in jam_lines:
                    self._log(f"  {ln[:200]}")
        except Exception as e_over_outer:
            print(f"Error resolving overset: {e_over_outer}")
            self._log(f"Error resolving overset: {e_over_outer}")

    def _finalize_layout(self, input_pages, clean_base=""):
        """Fit tables and images, centre graphics, inject the logo, and sync the TOC after reflow."""
        try:
            import paragraph_styles_format
            epub_file = os.path.join(self.epub_input_dir, f"{clean_base}.epub")
            ps_res = paragraph_styles_format.run(self.app, epub_file)
            print(f"Paragraph alignment & soft-break styles: {ps_res}")
            self._log(f"Paragraph styles: {ps_res}")
        except Exception as e_ps:
            self._log(f"Paragraph style pass note: {e_ps}")
        try:
            tbl_res = fix_table_fit.fix_tables_in_doc(self.app)
            print(f"Tables fixed: {tbl_res}")
            self._log(f"Tables fixed: {tbl_res}")
        except Exception as e_tbl:
            print(f"Table fix pass skipped: {e_tbl}")
            self._log(f"Table fix pass skipped: {e_tbl}")

        try:
            res_c = self.app.DoScript(js.center_all_js(), JS_LANG)
            self._log(f"Center sweep: {res_c}")
        except Exception as e:
            self._log(f"Center sweep failed: {e}")

        output_pages = 0
        try:
            output_pages = int(self.app.DoScript(js.page_count_js(), JS_LANG))
        except Exception:
            pass
        page_delta = output_pages - input_pages
        summary = f"Output pages: {output_pages} (added {page_delta} pages after injection)"
        print(summary)
        self._log(summary)

        try:
            imgs_fixed = fix_image_layout.fix_image_layout(self.app)
            print(f"Image layout fixed: {imgs_fixed} image(s) re-fitted within margins")
            self._log(f"Image layout fixed: {imgs_fixed}")
        except Exception as e_fil:
            print(f"Image layout pass skipped: {e_fil}")
            self._log(f"Image layout pass skipped: {e_fil}")

        try:
            centered = fix_image_layout.center_images_in_cells(self.app)
            print(f"Cell images centered: {centered}")
            self._log(f"Cell images centered: {centered}")
        except Exception as e_cic:
            print(f"Cell-centering pass skipped: {e_cic}")
            self._log(f"Cell-centering pass skipped: {e_cic}")

        try:
            borders_cleared = fix_image_layout.remove_image_table_borders(self.app)
            print(f"Image table borders cleared: {borders_cleared}")
            self._log(f"Image table borders cleared: {borders_cleared}")
        except Exception as e_brd:
            print(f"Border removal pass skipped: {e_brd}")
            self._log(f"Border removal pass skipped: {e_brd}")

        try:
            logo_done = logo_inject.inject_logo(self.app, self.logo_path)
            print(f"Logo relinked + fitted in original frame: {logo_done}")
            self._log(f"Logo injected: {logo_done}")
        except Exception as e_logo:
            print(f"Logo injection pass skipped: {e_logo}")
            self._log(f"Logo injection pass skipped: {e_logo}")

        try:
            repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            for p in (repo_dir, os.path.join(repo_dir, "book_workflow"), os.path.join(repo_dir, "book_workflow", "core")):
                if p not in sys.path:
                    sys.path.insert(0, p)
            try:
                from book_workflow.core.toc_synchronizer import sync_toc_via_indesign
            except ImportError:
                from toc_synchronizer import sync_toc_via_indesign
            toc_sync_count = sync_toc_via_indesign(self.app)
            print(f"Live InDesign TOC Sync: {toc_sync_count} entry(ies) synchronized with layout")
            self._log(f"TOC sync: {toc_sync_count} entries synchronized")
        except Exception as e_toc:
            print(f"TOC sync pass skipped: {e_toc}")
            self._log(f"TOC sync pass skipped: {e_toc}")

        try:
            # Real-layout front matter: chapters on an odd page, footer master from the real first content page.
            from book_workflow.core.frontmatter_flow import apply_frontmatter_flow, layout_changed
            ff_report = apply_frontmatter_flow(self.app)
            print(f"Front-matter flow: {ff_report}")
            self._log(f"Front-matter flow: {ff_report}")
            if layout_changed(ff_report):
                self.app.DoScript(js.resolve_overset_js(), JS_LANG)   # content moved a page: re-resolve overset
        except Exception as e_ff:
            print(f"Front-matter flow pass skipped: {e_ff}")
            self._log(f"Front-matter flow pass skipped: {e_ff}")

        try:
            v_res = self.app.DoScript(js.sanitize_vertical_justification_js(), JS_LANG)
            print(f"Vertical bottom-align: {v_res}")
            self._log(f"Vertical bottom-align: {v_res}")
        except Exception as e_v:
            self._log(f"Vertical bottom-align note: {e_v}")

    def _export(self, output_idml, fail_count):
        """Export the injected IDML, routing to the rejection folder when images were missing."""
        print("Exporting processed IDML to output folder...")
        if fail_count > 0:
            rejection_dir = os.path.join(os.path.dirname(self.output_idml_dir), "rejection_folder")
            os.makedirs(rejection_dir, exist_ok=True)
            output_idml = os.path.join(rejection_dir, os.path.basename(output_idml))
            print(f"MISSING IMAGES DETECTED. Exporting to REJECTION FOLDER: {output_idml}")
            self._log(f"REJECTED due to missing images. Exported to: {output_idml}")

        clean_output_idml = output_idml.replace(chr(92), "/")
        self.app.DoScript(js.export_js(clean_output_idml), JS_LANG)
        self._log(f"Exported To: {output_idml}")

    def _process_file(self, filename):
        """Run the full injection pipeline for one IDML; return True when finished (or deliberately skipped)."""
        idml_path = os.path.join(self.input_dir, filename)
        base_name = os.path.splitext(filename)[0]
        clean_base = base_name.replace("_normalized", "").replace("_formatted", "")

        if self._already_injected(idml_path, clean_base, base_name):
            print(f"SKIP (already injected): {filename}", flush=True)
            self._log(f"SKIP already injected: {filename}")
            return True

        current_image_folder = os.path.join(self.base_image_dir, clean_base)
        caption_map, caption_styles = self._extract_epub(clean_base, base_name, current_image_folder)
        output_idml = os.path.join(self.output_idml_dir, f"{clean_base}_injected.idml")

        doc_temp_dir = os.path.join(self.output_dir, "_resized", clean_base)
        if os.path.exists(doc_temp_dir):
            shutil.rmtree(doc_temp_dir, ignore_errors=True)
        os.makedirs(doc_temp_dir, exist_ok=True)

        print(f"\n{'-'*50}")
        print(f"Processing Document: {filename}")
        print(f"Using Image Folder: {current_image_folder}")
        self._log(f"\n--- Document: {filename} ---")
        self._log(f"Image Folder: {current_image_folder}")

        input_pages = self._open_document(idml_path)
        print(f"Input pages: {input_pages}")
        self._log(f"Input pages: {input_pages}")

        fail_count = self._inject_images(clean_base, current_image_folder, doc_temp_dir)
        self._run_caption_passes(caption_map, caption_styles)
        self._run_layout_passes()
        self._resolve_overset(base_name, filename)
        self._finalize_layout(input_pages, clean_base)
        self._export(output_idml, fail_count)
        self.app = unpin_document(self.app)
        return True

    def _handle_doc_error(self, filename, retry_counts, exc):
        """React to a per-document failure; return True to retry the file, False to move on."""
        if not is_rpc_error(exc):
            print(f"[!] Error processing {filename}: {exc}", flush=True)
            self._log(f"ERROR on {filename}: {exc}")
            return False

        retry_counts[filename] += 1
        print(f"[!] InDesign hung/crashed on {filename} (attempt {retry_counts[filename]}/{MAX_RETRIES_PER_DOC}): {exc}", flush=True)
        self._log(f"HANG on {filename}: attempt {retry_counts[filename]} — {exc}")

        try:
            self.app = restart_indesign()
        except Exception as ridx:
            print(f"[!] Restart failed: {ridx}", flush=True)
            self._log(f"Restart failed for {filename}: {ridx}")
            return False

        try:
            partial = os.path.join(self.output_dir, f"{os.path.splitext(filename)[0]}_injected.idml")
            if os.path.exists(partial):
                os.remove(partial)
        except Exception:
            pass

        if retry_counts[filename] < MAX_RETRIES_PER_DOC:
            print(f"    Retrying {filename} from the start ...", flush=True)
            return True
        print(f"    Giving up on {filename} after {MAX_RETRIES_PER_DOC} attempts.", flush=True)
        self._log(f"GAVE UP on {filename} after {MAX_RETRIES_PER_DOC} hangs.")
        return False

    def run(self):
        """Connect to InDesign and process every selected IDML, retrying documents that hang."""
        self.app = connect_indesign()
        if self.app is None:
            print("Error: Could not connect to Adobe InDesign after multiple attempts.")
            return

        idml_files = self._build_file_list()
        if not idml_files:
            print(f"No IDML files found in: {self.input_dir}")
            return

        self.log_data = [
            "=== Batch IDML Processing Log ===",
            f"Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "-" * 40,
        ]
        print(f"Found {len(idml_files)} IDML file(s). Starting batch process...")

        retry_counts = {}
        _total = len(idml_files)
        for _i, filename in enumerate(idml_files, 1):
            print(f"\n[{_i}/{_total}] Injecting: {filename}")
            retry_counts.setdefault(filename, 0)
            while True:
                try:
                    self._process_file(filename)
                    break
                except Exception as doc_err:
                    if not self._handle_doc_error(filename, retry_counts, doc_err):
                        break

        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write("\n".join(self.log_data))

        print(f"\n{'-'*50}")
        print(f"Batch processing complete! Log saved to: {self.log_file}")


def process_batch_idmls(input_dir=None, epub_input_dir=None, output_dir=None,
                        output_idml_dir=None, logo_path=None, target_files=None):
    """Backward-compatible entry point: build an EpubInjector and run the batch."""
    EpubInjector(
        input_dir=input_dir,
        epub_input_dir=epub_input_dir,
        output_dir=output_dir,
        output_idml_dir=output_idml_dir,
        logo_path=logo_path,
        target_files=target_files,
    ).run()


if __name__ == "__main__":
    process_batch_idmls()
