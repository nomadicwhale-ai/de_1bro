# Conformance probe (R, base only). NOT RUN in the authoring environment.
kv <- function(k, v) cat(k, "=", v, "\n", sep = "")
probe <- function(k, f) {
  r <- tryCatch(f(), error = function(e) "error")
  kv(k, r)
}
fmt17 <- function(x) {
  if (is.nan(x)) return("nan")
  if (is.infinite(x)) return(if (x > 0) "inf" else "-inf")
  sprintf("%.17g", x)
}
strprobe <- function(p, s) {
  kv(paste0(p, "_utf8"), nchar(s, type = "bytes"))
  kv(paste0(p, "_utf16"), length(utf8ToInt(s)) + sum(utf8ToInt(s) > 65535))
  kv(paste0(p, "_scalars"), nchar(s, type = "chars"))
}
kv("lang", "r")
kv("version", R.version.string)
kv("size_int8", "n/a"); kv("size_int16", "n/a")
kv("size_int32", 4)          # integer is 32-bit
kv("size_int64", "n/a")      # no base 64-bit integer
for (n in c("uint8", "uint16", "uint32", "uint64")) kv(paste0("size_", n), "n/a")
kv("size_float32", "n/a")
kv("size_float64", 8)        # numeric is a double
kv("size_bool", 4)           # logical is stored as a 32-bit int
kv("size_char", "n/a")
kv("char_meaning", "no char type; a character vector element is a string")
probe("int32_max_plus_1", function() { x <- suppressWarnings(.Machine$integer.max + 1L); if (is.na(x)) "NA" else as.character(x) })
probe("int64_max_plus_1", function() "n/a")
probe("uint8_255_plus_1", function() "n/a")
probe("uint32_0_minus_1", function() "n/a")
probe("int_div_m7_2", function() as.character(-7L %/% 2L))
probe("int_mod_m7_2", function() as.character(-7L %% 2L))
probe("int_div_by_zero", function() { x <- 1L %/% 0L; if (is.na(x)) "NA" else as.character(x) })
probe("f64_0_1_plus_0_2", function() fmt17(0.1 + 0.2))
probe("f32_16777217_roundtrip", function() "n/a")
probe("f64_2p53_plus_1", function() fmt17(9007199254740992 + 1))
probe("f64_nan_eq_nan", function() { x <- NaN == NaN; if (is.na(x)) "NA" else tolower(as.character(x)) })
fz <- 0
probe("f64_1_div_0", function() fmt17(1 / fz))
probe("f64_neg1_div_0", function() fmt17(-1 / fz))
probe("f64_0_div_0", function() fmt17(fz / fz))
probe("i64_2p53p1_via_f64", function() "n/a")
strprobe("str_e_pre", "é")
strprobe("str_e_comb", "é")
strprobe("str_emoji", "\U0001F600")
probe("date_epoch_day_2015_01_01", function() as.character(as.integer(as.Date("2015-01-01"))))
kv("timestamp_max_precision", "us")  # POSIXct is a double of seconds: ~microsecond resolution
probe("empty_array_index0", function() { x <- numeric(0)[1]; if (is.na(x)) "NA" else as.character(x) })
probe("empty_array_max", function() as.character(suppressWarnings(max(numeric(0)))))
probe("empty_string_index0", function() { x <- substr("", 1, 1); if (x == "") "empty_string" else x })
probe("empty_string_split_count", function() as.character(length(strsplit("", ",")[[1]])))
probe("map_order_3_1_2", function() { e <- new.env(hash = TRUE); for (k in c("3", "1", "2")) assign(k, 0, envir = e); paste(ls(e, sorted = FALSE), collapse = ",") })
kv("decimal_0_1_plus_0_2", "n/a")
probe("f64_sum_10m_0_1", function() { s <- 0; a <- 0.1; for (i in 1:10000000) s <- s + a; fmt17(s) })
