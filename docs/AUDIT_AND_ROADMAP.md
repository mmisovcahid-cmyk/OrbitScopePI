# OrbitScope — Audit və Yol Xəritəsi

*Tarix: 2026-11-11 · Branch: `dev/full-system`*

## 0. Vəziyyət (2026-11-12)

| Faza | Vəziyyət |
|---|---|
| **0 — Təmizlik** | ✅ Detection route səhvi düzəldildi və `pipeline_manager` singleton-u əlavə olundu, real pipeline artıq işləyir (sintetik kadrlarda, `[SIMULATED]` etiketi ilə). Port 5173-ə keçirildi, code-splitting əlavə olundu, naviqasiya i18n-ə keçirildi, işləməyən tema düyməsi silindi, səhifələrə padding və mobil naviqasiya əlavə olundu. ⏳ ESLint quraşdırılmayıb. |
| **1 — Real SPHEREx blink MVP** | ✅ Hazırdır, 5 sınaq hədəfində yoxlanıldı. ⚠️ WISE 0855 D6-da çox zəifdir: hər keçidə 4 ekspozisiya toplandıqda gözlə görmək çətindir. |
| 2 — Elmi alətlər | ✅ Fərq, Hərəkət rəngi, Cəm (stack) rejimləri. ✅ Gaia DR3 və CatWISE2020 overlay-i: markerlər proper motion ilə hər kadrın tarixinə köçürülür, ulduz ölçüsü süzgəci var, CatWISE artefaktları süzülür. ✅ Hədəf və ya kliklənmiş nöqtə üçün aperture fotometriyası: hər pikselin LVF dalğa uzunluğu ilə 0.75–5 µm spektr və işıq əyrisi. ε Indi B-də real T-cırtdan spektri alındı (H₂O 1.4 µm, CH₄, CO 4.6 µm udulmaları görünür). ⚠️ Çox parlaq ulduzlar (R Dra, Barnard) SPHEREx-də doyur, onların ölçmələri "doymuş" kimi işarələnir. ⏳ Aladin Lite (CDS servisləri hazırda əlçatmazdır). |
| 3 — Real məlumatda aşkarlama | ✅ Detection səhifəsi artıq real SPHEREx məlumatı ilə işləyir (ətraflı nəticələr aşağıda, bölmə 6). |
| 6 — Audit düzəlişləri (2026-11-13) | ✅ WISE 0855: 8.2″/il, 7.6σ, CatWISE ilə uyğun (tam DR1 örtüyü); zəif hədəflər üçün "forced" astrometriya əlavə olundu. ✅ Asteroid axtarışında keyfiyyət qaydaları: Notburga sahəsində yalançı `unknown_mover` 8+2 → 0, Notburga yenə tapılır. ✅ PM-də xəttilik yoxlaması (ε Indi B-dəki 19.6″/il şübhəli namizəd yox oldu). ✅ IRSA-da faylı olmayan QR2 kadrları yadda saxlanılır və əvəz olunur; köhnə örtük keşi (QR2) avtomatik yenilənir (bu səbəbdən WISE 0855 əvvəl D1–D5-də açılmırdı). ✅ Startup prewarm, 3 demo axtarış, Aladin Lite, dalğa zolağı filtri, Planet X üçün tam SBDB nümunəsi (59 obyekt, p≈0.02) ədəbiyyat nümunəsi (20, p≈5×10⁻⁴) ilə yanaşı. ✅ Koordinatla daxil edilən çağırış hədəfləri tanınır. ✅ Review tokeni, lokallaşdırılmış 422 xətaları, NASA loqosu çıxarıldı, ölü kod təmizləndi. ✅ Docker build və işə salma yoxlanıldı. |
| 5 — Münsiflərə hazırlıq (2026-11-13) | ✅ Simulyasiya edilmiş məlumat yaradan bütün köhnə kod silindi: `sky`, `observations`, `detection` router-ləri, `demo_data`, köhnə JPL/IRSA klientləri, photutils pipeline-ı və `ml/`. İndi heç bir endpoint uydurma məlumat vermir. ✅ `scripts/prewarm.py` 5 test hədəfinin keşini əvvəlcədən doldurur. ✅ Bahalı sorğulara rate limit qoyuldu (dəqiqədə 60), Docker-də `DEBUG=false`. ✅ METHODOLOGY, ARCHITECTURE, LIMITATIONS, REFERENCES və README real sistemə uyğun yenidən yazıldı. ✅ MIT LICENSE əlavə olundu. ⏳ Public hosting və GitHub repo komandanın seçimidir. ⏳ Aladin Lite və Blink-də band filtri hələ yoxdur. |
| 4 — İstehsal | ✅ Fon tapşırıqları: mərhələ, irəliləyiş sayğacı, ləğv etmə, eyni sorğuların birləşdirilməsi. ✅ `/api/v1/spherex/status` sağlamlıq endpoint-i. ✅ Keşin ölçü limiti və avtomatik təmizlənməsi. ✅ ESLint 9 (0 xəta). ✅ Real SPHEREx FITS fixture-ləri ilə testlər. ✅ Dockerfile-lar, nginx və docker-compose. ⚠️ Docker bu kompüterdə quraşdırılmadığı üçün image build yoxlanılmayıb; nginx proxy məntiqi `vite preview` ilə eyni domen rejimində yoxlanılıb. |

## 1. Çağırışın tələbi (qısa)

İstifadəçi RA/Dec daxil edir → alət həmin sahənin **SPHEREx şəkillərini zaman ardıcıllığı ilə qısa video (blink) kimi** göstərir → hərəkət edən obyektlər gözlə asan görünür.
Sınaq hədəfləri: **Barnard ulduzu, Epsilon Indi B, WISE 0855−0714, RW Aurigae, R Draconis**.
Əlavə (məcburi deyil): yeni buraxılışlarla avtomatik yenilənmə, 102 zolağın/6 detektorun yaradıcı istifadəsi, spektr, epoxaları toplamaq/çıxmaq, baxış sahəsi seçimi, Gaia/WISE overlay, URL ilə sorğu (embed), çirklənmə bayraqları, Astropy/Aladin istifadəsi.

## 2. Sistem hazırda nə edir?

Görünüşcə tam platformadır (FastAPI + React, 7 səhifə, EN/AZ), amma **real SPHEREx şəkli heç yerdə göstərilmir**. Faktiki olaraq bu, demo məlumatla işləyən bir UI qabığıdır.

| Sahə | Vəziyyət |
|---|---|
| SPHEREx məlumat qatı | ❌ `irsa_client` mövcud olmayan `spherex_source` / `spherex_image` cədvəllərini sorğulayır → həmişə boş → həmişə sintetik məlumat. Real cədvəllər: `spherex.obscore`, `spherex.plane`, `spherex.artifact`... |
| Şəkillər | ❌ `get_observation_image` həmişə sintetik ulduz sahəsi yaradır (`spherex_data.py:203`). `DEMO_MODE=false` olsa belə şəkil yükləmə kodu yoxdur. |
| Detection pipeline | ❌ Route `pipeline_manager.run_detection(payload)` çağırır, amma metod `observation_ids: list` gözləyir → `TypeError` → həmişə saxta `_create_fallback_pipeline_result` qaytarılır (`detection.py:139`). Düzəldilsə belə pipeline sabit Orion koordinatlarında (83.633, 22.014) sintetik kadrlar istifadə edir (`pipeline_manager.py:121`). |
| Müqayisə səhifəsi | ❌ Koordinatlar sabit kodlanıb (`ComparisonPage.tsx:24` → 83.82, −5.39). |
| Sky Map | ⚠️ Psevdo-təsadüfi ulduzlarla Canvas; real səma deyil. Aladin yoxdur. |
| **Blink / video görünüşü** (əsas tələb) | ❌ Yoxdur. |
| Ad ilə axtarış (məs. "Barnard's Star") | ❌ Yoxdur. |
| URL parametrləri / embed | ❌ Yoxdur. |
| Gaia/WISE overlay, bayraqlar, spektr | ❌ Yoxdur. |
| JPL SBDB/Horizons | ✅ Real API çağırışları var (fallback ilə). |
| i18n EN/AZ | ✅ İşləyir. |
| Testlər | ✅ 50/50 keçir — amma əsasən mock yolları yoxlayır. |
| Frontend build | ✅ Keçir (bundle 790 KB, code-splitting yoxdur). |
| Kiçik problemlər | `npm run lint` işləmir (ESLint quraşdırılmayıb); port uyğunsuzluğu (README 5173 / vite 3000); bütün vəziyyət yaddaşdadır, restartda itir. |

**Nəticə:** UI, i18n, JPL inteqrasiyası və pipeline modulları (photutils, alignment, subtraction) yenidən istifadə oluna bilər. Məlumat qatı isə sıfırdan yazılmalıdır, əsas funksiya olan blink görünüşü də yaradılmalıdır.

## 3. Real SPHEREx məlumatı — yoxlanılıb ✅

Audit zamanı IRSA ilə canlı yoxlama apardım:

- **TAP:** `spherex.obscore` cədvəli var. `CONTAINS(POINT('ICRS', ra, dec), s_region)=1` sorğusu nöqtəni əhatə edən bütün kadrları qaytarır.
- **Barnard ulduzu (269.452, +4.693):** **364 kadr**, kolleksiyalar `spherex_qr2` (241) + `spherex_qr3` (123), 6 detektorun hamısı (D1–D6, ~60 kadr hər biri). Zaman aralığı **MJD 60902 → 61305 (~2025-08-15 → 2026-09-22)**, yəni ~3 tam səma keçidi.
- **Cutout:** L2 FITS URL-inə `?center=ra,dec&size=0.1` əlavə etməklə IBE cutout işləyir. 0.1° ≈ 58×58 piksel (≈6.2″/piksel). Extension-lar: `IMAGE` (MJy/sr), `FLAGS`, `VARIANCE`, `ZODI`, `PSF` (121×101×101), `WCS-WAVE`.
- ⚠️ **Hər cutout ~5 MB-dır**, çünki PSF kubu da gəlir. 364 kadr × 5 MB ≈ 1.8 GB, ona görə kadr seçimi, paralel yükləmə və disk keşi vacibdir.
- **Hərəkətin miqyası:** Barnard ~10.3″/il ≈ 1.7 piksel/il, WISE 0855 ~8″/il, ε Indi B ~4.7″/il. Bir il ərzindəki yerdəyişmə kiçikdir, ona görə epoxa üzrə coadd (S/N artımı), fərq şəkli və Gaia proqnoz markerləri lazımdır.
- **Spektral qeyd:** SPHEREx LVF (linear variable filter) istifadə edir, dalğa uzunluğu detektor üzrə dəyişir. Hər piksel üçün dalğa uzunluğu `WCS-WAVE`-dən alınır. Bir mənbənin bütün kadrlardakı fotometriyası birləşdirilsə 0.75–5 µm spektri alınır.
- Kolleksiya adları sabit kodlanmamalıdır: `obs_collection LIKE 'spherex%'` ilə yeni buraxılışlar (qr4, ...) avtomatik daxil olacaq.

## 4. Yol xəritəsi

### Faza 0 — Təmizlik (½ gün)
- Detection route-dakı signature səhvini düzəltmək; saxta fallback nəticələri yalnız açıq demo rejimində və `[SIMULATED]` etiketi ilə qaytarmaq.
- Port uyğunsuzluğunu, ESLint-i və bundle code-splitting-i düzəltmək.
- `DEMO_MODE` default olaraq `false`; demo yalnız şəbəkə xətasında, aydın etiketlə.

### Faza 1 — MVP: real SPHEREx blink aləti (əsas tələb) — 3–4 gün
**Backend** (`app/services/spherex/` yeni modul):
1. `query_frames(ra, dec, start?, end?, detectors?)`: `spherex.obscore` sorğusu (kolleksiya, MJD, detektor, λ aralığı).
2. `fetch_cutout(frame, ra, dec, size)`: IBE cutout, `httpx` ilə paralel (limitli), FITS-in diskdə keşlənməsi (`cache/spherex/<obs_id>_<ra>_<dec>_<size>.fits`).
3. `build_epochs(frames)`: kadrları zamana görə epoxalara (vizitlərə) qruplaşdırmaq; hər epoxa+detektor üçün `FLAGS` maskası, `ZODI` çıxılması, inverse-variance coadd.
4. `reproject` (astropy-reproject) ilə hədəf mərkəzli ortaq TAN şəbəkəsinə köçürmək, belə ki bütün kadrlar piksel-piksel üst-üstə düşür.
5. Stretch (zscale/asinh, bütün kadrlar üçün eyni), PNG kadrlar + animasiyalı GIF/WebP.
6. API: `GET /api/v1/spherex/frames?ra&dec&fov&detector&mode=epoch|single` → metadata + kadr URL-ləri; `GET /api/v1/spherex/animation.gif?...`.
7. Ad həlli: `GET /api/v1/resolve?name=` (CDS Sesame).

**Frontend** (yeni "Blink" səhifəsi, ana səhifə olacaq):
- Koordinat girişi (onluq + `08h55m10.831s -7d14m42.53s` formatı) + obyekt adı ilə axtarış.
- FOV slayderi, detektor/zolaq seçimi, oynat/dayandır/sürət/addım, kadr başına tarix, detektor, λ, bayraq sayı.
- URL sinxronizasiyası: `/?ra=…&dec=…&fov=…`; `/embed?...` (iframe üçün minimal görünüş).
- 5 sınaq hədəfi üçün hazır düymələr.

**Qəbul meyarı:** 5 hədəfin hər biri üçün real SPHEREx blink açılır; Barnard və WISE 0855-in yerdəyişməsi görünür; RW Aur / R Dra-nın parlaqlıq dəyişməsi görünür.

### Faza 2 — Elmi alətlər (3–4 gün)
- **Epoxa riyaziyyatı:** A−B fərq şəkli, seçilmiş epoxaların cəmi və median, "hərəkət rəngi" (epoxa 1 = qırmızı, epoxa N = mavi RGB kompozit).
- **Overlay-lər:** Aladin Lite v3 (CDS) ilə Gaia DR3, AllWISE/unWISE HiPS; Gaia proper motion ilə hər epoxa üçün proqnoz mövqe markerləri.
- **Bayraqlar:** `FLAGS` bitlərinin rəngli maska kimi göstərilməsi və hər bit üçün izah.
- **Spektr:** kliklənən pikseldə bütün kadrlardan fotometriya + `WCS-WAVE` → λ, yəni 0.75–5 µm spektr qrafiki (Recharts).
- **İşıq əyrisi:** dəyişkən ulduzlar üçün zaman üzrə parlaqlıq.

### Faza 3 — Real məlumatda hərəkətli obyekt aşkarlanması (3 gün)
- Mövcud pipeline-ı (preprocessor, source_detector, subtractor, associator) real reproject olunmuş epoxa kadrlarına qoşmaq; sintetik WCS-i silmək.
- Məlum kiçik cisimlər: hər epoxa üçün JPL **SB Ident** API ilə sahədəki asteroid və kometlərin overlay-i.
- Namizədlər üçün "Bunu işarələ" axını (vətəndaş elmi), namizədlərin SQLite-da saxlanması.

### Faza 4 — İstehsala hazırlıq (2 gün)
- Yeni buraxılışların avtomatik aşkarlanması (status endpoint-də kolleksiya siyahısı, keşin TTL-i).
- Uzun yükləmələr üçün fon tapşırıqları + irəliləyiş göstəricisi (SSE).
- Docker / docker-compose, real FITS fixture-ləri ilə testlər (şəbəkəsiz).
- README və docs yeniləmələri.

### Prioritetdən sonraya qalanlar
Planet X səhifəsi, ML anomaliya skorlaması və mövcud Dashboard qalır, amma əsas axın deyil. Naviqasiyada Blink alətindən sonra yerləşəcəklər.

## 5. Əsas risklər

| Risk | Azaltma |
|---|---|
| Cutout həcmi (~5 MB/kadr) və IRSA sürəti | Epoxa+detektor üzrə kadr limiti, paralel limit (4–6), disk keşi, irəliləyiş göstəricisi |
| Kiçik yerdəyişmə (≤2 piksel/il) | Coadd ilə S/N artımı, fərq şəkli, Gaia proqnoz markerləri, böyüdülmüş (upsampled) görünüş |
| Parlaq ulduzlarda doyma (Barnard) | `FLAGS` maskası, uzun dalğa detektorlarının (D5–D6) seçimi |
| LVF: kadrlar arasında dalğa uzunluğu fərqi | Default olaraq eyni detektorun kadrlarını müqayisə etmək; λ hər kadrda göstərilir |

## 6. Faza 3 — Real məlumatda hərəkətli obyekt aşkarlanması (nəticələr)

### Necə işləyir
- **Asteroidlər və kometlər.** Bir müşahidə keçidinin ayrı ekspozisiyalarından istifadə olunur.
  - SPHEREx eyni sahəni ~2 dəqiqə fasiləli 4 ekspozisiyalıq ziyarətlərlə çəkir. D1/D4, D2/D5 və D3/D6 detektorları eyni anda çəkir.
  - Hər detektor üçün median "sabit səma" şablonu qurulur və hər kadrdan çıxılır.
  - Qalıqlar yalnız bir ziyarət daxilində birləşdirilir, sonra ziyarətlər arasında xətti hərəkət yoxlanılır.
  - Əlavə süzgəclər: səs-küylü kadrlar atılır, eyni nöqtədə təkrarlanan qalıqlar (persistence, dəyişkən mənbələr) "stasionar keçici" kimi rədd edilir.
  - Hər trek NASA/JPL SB Ident ilə müqayisə olunur.
- **Xüsusi hərəkət (ulduzlar, qəhvəyi cırtdanlar).** Hər keçid üçün dərin toplanmış şəkil istifadə olunur.
  - Fərq şəkli yox, **astrometriya** tətbiq edilir: hər ulduzun mərkəzi hər epoxada ölçülür, kadr üzrə qeydiyyat xətası çıxılır, əhəmiyyət sabit ulduzlardan ölçülən səs-küyə görə hesablanır.
  - Gaia DR3 və CatWISE2020 ilə müqayisə yalnız PM vektoru uyğun gələndə qəbul olunur.
- **Namizədlər** SQLite-da saxlanılır. İstifadəçi onları "Real / Artefakt / Əmin deyiləm" kimi qiymətləndirə və CSV ilə ixrac edə bilər.

### Real məlumatda yoxlama
| Test | Nəticə |
|---|---|
| 626 Notburga (V=13.5), 2025-06/07 keçidi | ✅ Tapıldı: 8 aşkarlama (D1+D4), trek RMS 0.11 px, JPL proqnozundan **1.6″**, ölçülən sürət 58″/saat |
| Ekliptika sahəsi 00h40m +04° (V≤18: 2 obyekt) | 0 saxta "yeni hərəkətli". Əvvəlcə uyğunlaşan qalıq stasionarlıq yoxlamasında rədd edildi |
| ε Indi B (PM) | ✅ 4.1″/il, PA 123° (həqiqi 4.7″/il, 122°), 15σ, Gaia DR3 uyğunluğu |
| WISE 0855−0714 (PM) | ✅ 7.9″/il, PA 280° (həqiqi 8.2″/il, 275°), 6σ, CatWISE uyğunluğu |
| Barnard, RW Aur, R Dra | ⚠️ SPHEREx-də doyurlar, astrometriya/fotometriyadan qəsdən çıxarılır (Blink və Hərəkət rəngi rejimlərində görünürlər) |

### Məhdudiyyətlər
- Tək ekspozisiya həssaslığı V≈17–18 ətrafındadır, daha zəif asteroidlər adətən tapılmır.
- Dworetsky (V=17.2) tapılmadı.
- PM üçün 0.25 px-dən (≈1.5″) kiçik ümumi yerdəyişmə ölçülə bilmir.
- Namizədlər kəşf deyil: əlavə müşahidə və MPC-yə bildiriş lazımdır.
