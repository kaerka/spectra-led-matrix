// whisper-npu-host: persistent host process for Qualcomm VoiceAI Whisper on the
// Hexagon NPU (QCS6490 / Hexagon V68).
//
// Three modes:
//   batch       -- transcribe a list of wav files, emit TSV with timings (benchmarking)
//   stream      -- read s16le mono 16 kHz PCM on stdin, emit one JSON object per line
//                  as the VAD closes each utterance (live audio, sub-second latency)
//   serve-files -- read one wav path per line on stdin, emit one JSON result per
//                  line; this is what bridges/whisper/asr_npu.py drives
//
// The Qualcomm SDK libraries print diagnostics to stdout too, so a parent must
// skip lines that are not JSON objects.
//
// The SDK sample initialises the model, handles one input, and exits. Driving it
// per-utterance costs a ~1 s init each time, and killing it mid-run leaks a
// FastRPC compute session on the DSP -- there are only 12, after which the DSP
// wedges badly enough that stopping the remoteproc fails. So this process
// initialises once, reuses the session, and always calls deInit() including on
// SIGINT/SIGTERM.

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cstdint>
#include <cerrno>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>

#include "InputStream.h"
#include "Whisper.h"
#include "WhisperResponseListener.h"

using namespace WhisperFunction;
using Clock = std::chrono::steady_clock;

namespace {

Whisper gWhisper;
std::atomic<bool> gInitialised{false};
std::atomic<bool> gShutdown{false};

void releaseAndExit(int sig) {
    gShutdown = true;
    if (gInitialised.exchange(false)) {
        gWhisper.stop();
        gWhisper.deInit();
    }
    std::_Exit(sig == 0 ? 0 : 128 + sig);
}
void onSignal(int sig) { releaseAndExit(sig); }

long wavDurationMs(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return -1;
    char hdr[44];
    if (!f.read(hdr, sizeof(hdr))) return -1;
    if (std::memcmp(hdr, "RIFF", 4) != 0 || std::memcmp(hdr + 8, "WAVE", 4) != 0) return -1;
    uint32_t rate; uint16_t ch, bits;
    std::memcpy(&ch, hdr + 22, 2); std::memcpy(&rate, hdr + 24, 4); std::memcpy(&bits, hdr + 34, 2);
    f.seekg(0, std::ios::end);
    long bytes = static_cast<long>(f.tellg()) - 44;
    long bps = static_cast<long>(rate) * ch * (bits / 8);
    return bps > 0 ? bytes * 1000 / bps : -1;
}

std::string flatten(std::string s) {
    for (char& c : s) if (c == '\t' || c == '\n' || c == '\r') c = ' ';
    size_t b = s.find_first_not_of(' '), e = s.find_last_not_of(' ');
    return b == std::string::npos ? std::string() : s.substr(b, e - b + 1);
}

std::string jsonEscape(const std::string& s) {
    std::string o; o.reserve(s.size() + 8);
    for (unsigned char c : s) {
        switch (c) {
            case '"':  o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n";  break;
            case '\r': o += "\\r";  break;
            case '\t': o += "\\t";  break;
            default:
                if (c < 0x20) { char b[7]; std::snprintf(b, sizeof(b), "\\u%04x", c); o += b; }
                else o += static_cast<char>(c);
        }
    }
    return o;
}

class Listener : public WhisperResponseListener {
public:
    // Streaming mode prints each result as it arrives; batch mode accumulates.
    void setStreaming(bool v) { mStreaming = v; }
    void setEpoch(Clock::time_point t) { mEpoch = t; }

    void reset() {
        std::lock_guard<std::mutex> lk(mMutex);
        mText.clear(); mLang.clear(); mFinal = false; mError = 0;
    }

    void onTranscription(std::map<std::string, std::string> const& r) override {
        std::string text, lang, isFinal;
        auto get = [&](const std::string& k) {
            auto it = r.find(k); return it == r.end() ? std::string() : it->second;
        };
        text = flatten(get(KEY_TRANSCRIPTION));
        lang = get(KEY_LANGUAGE);
        isFinal = get(KEY_IS_FINAL);
        bool fin = (isFinal == "1" || isFinal == "true");

        if (mStreaming) {
            if (text.empty()) return;
            auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - mEpoch).count();
            std::lock_guard<std::mutex> lk(mOutMutex);
            std::cout << "{\"type\":\"" << (fin ? "final" : "partial")
                      << "\",\"text\":\"" << jsonEscape(text)
                      << "\",\"language\":\"" << jsonEscape(lang)
                      << "\",\"t_ms\":" << ms << "}\n";
            std::cout.flush();
            return;
        }

        std::lock_guard<std::mutex> lk(mMutex);
        if (!text.empty()) mText = text;
        if (!lang.empty()) mLang = lang;
        if (fin) { mFinal = true; mCv.notify_all(); }
    }

    void onEvent(int event) override {
        if (!mStreaming) return;
        std::lock_guard<std::mutex> lk(mOutMutex);
        std::cout << "{\"type\":\"event\",\"code\":" << event << "}\n";
        std::cout.flush();
    }

    void onError(int error) override {
        if (mStreaming) {
            std::lock_guard<std::mutex> lk(mOutMutex);
            std::cout << "{\"type\":\"error\",\"code\":" << error << "}\n";
            std::cout.flush();
            return;
        }
        std::lock_guard<std::mutex> lk(mMutex);
        mError = error; mFinal = true; mCv.notify_all();
    }

    bool wait(int timeoutMs) {
        std::unique_lock<std::mutex> lk(mMutex);
        return mCv.wait_for(lk, std::chrono::milliseconds(timeoutMs), [&] { return mFinal; });
    }
    std::string text() { std::lock_guard<std::mutex> lk(mMutex); return mText; }
    std::string lang() { std::lock_guard<std::mutex> lk(mMutex); return mLang; }
    int error()        { std::lock_guard<std::mutex> lk(mMutex); return mError; }

private:
    std::mutex mMutex, mOutMutex;
    std::condition_variable mCv;
    std::string mText, mLang;
    bool mFinal = false, mStreaming = false;
    int mError = 0;
    Clock::time_point mEpoch = Clock::now();
};

void usage() {
    std::cout <<
      "whisper-npu-host -- Whisper on the Hexagon NPU\n\n"
      "  --model DIR          model dir (encoder/decoder/vocab/speech_float.eai)  [required]\n"
      "  --lang CODE          language code, or 'auto' to detect (default auto)\n"
      "  --translate          enable the SDK translate task (NOTE: returns empty on this model)\n"
      "  --languages          print supported language codes and exit\n"
      "\nbatch mode:\n"
      "  --list FILE          one wav path per line\n"
      "  --wav FILE           a single wav file\n"
      "  --out FILE           TSV output (default stdout)\n"
      "  --timeout MS         per-clip timeout (default 60000)\n"
      "\nstream mode:\n"
      "  --stream             read s16le mono 16kHz PCM on stdin, emit JSON lines on stdout\n"
      "\nserve mode (one warm process, driven by a parent):\n"
      "  --serve-files        read a wav path per line on stdin, emit one JSON result per line\n"
      "  --partials           also emit interim (non-final) results\n"
      "  --min-buffer-ms N    minimum audio buffered before inference\n"
      "  --vad-threshold N    VAD energy threshold (q20)\n"
      "  --vad-hangover N     VAD hangover length\n"
      "  --chunk-bytes N      stdin read size (default 8192 = 256ms)\n";
}

} // namespace

int main(int argc, char** argv) {
    std::string modelDir, listFile, wavFile, lang = "auto", outFile;
    bool translate = false, dumpLangs = false, stream = false, partials = false;
    bool serveFiles = false;
    int timeoutMs = 60000, minBufferMs = -1, vadThreshold = -1, vadHangover = -1;
    size_t chunkBytes = 8192;

    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() -> std::string { return (i + 1 < argc) ? argv[++i] : std::string(); };
        if      (a == "--model")          modelDir = next();
        else if (a == "--list")           listFile = next();
        else if (a == "--wav")            wavFile = next();
        else if (a == "--lang")           lang = next();
        else if (a == "--out")            outFile = next();
        else if (a == "--translate")      translate = true;
        else if (a == "--languages")      dumpLangs = true;
        else if (a == "--stream")         stream = true;
        else if (a == "--serve-files")    serveFiles = true;
        else if (a == "--partials")       partials = true;
        else if (a == "--timeout")        timeoutMs = std::stoi(next());
        else if (a == "--min-buffer-ms")  minBufferMs = std::stoi(next());
        else if (a == "--vad-threshold")  vadThreshold = std::stoi(next());
        else if (a == "--vad-hangover")   vadHangover = std::stoi(next());
        else if (a == "--chunk-bytes")    chunkBytes = static_cast<size_t>(std::stoul(next()));
        else if (a == "-h" || a == "--help") { usage(); return 0; }
        else { std::cerr << "unknown argument: " << a << "\n"; usage(); return 2; }
    }

    if (dumpLangs) {
        auto codes = Whisper::getSupportedLanguageCodes();
        auto names = Whisper::getSupportedLanguages();
        std::cout << "supported languages: " << codes.size() << "\n";
        for (size_t i = 0; i < codes.size(); ++i)
            std::cout << codes[i] << "\t" << (i < names.size() ? names[i] : std::string()) << "\n";
        return 0;
    }

    if (modelDir.empty() || (!stream && !serveFiles && listFile.empty() && wavFile.empty())) { usage(); return 2; }
    if (modelDir.back() != '/') modelDir += '/';

    std::signal(SIGINT, onSignal);
    std::signal(SIGTERM, onSignal);
    std::signal(SIGPIPE, SIG_IGN);

    std::map<std::string, std::string> paths;
    paths[Whisper::KEY_MODEL_FILE_ENCODER] = modelDir + "encoder_model_htp.bin";
    paths[Whisper::KEY_MODEL_FILE_DECODER] = modelDir + "decoder_model_htp.bin";
    paths[Whisper::KEY_VOCAB_FILE]         = modelDir + "vocab.bin";
    paths[Whisper::KEY_PATH_VAD_MODEL]     = modelDir + "speech_float.eai";
    paths[Whisper::KEY_PATH_ADSP]          = modelDir;

    auto t0 = Clock::now();
    if (!gWhisper.init(paths)) { std::cerr << "whisper init failed\n"; return 1; }
    gInitialised = true;
    auto initMs = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - t0).count();
    std::cerr << "init_ms=" << initMs << " sdk=" << gWhisper.getVersion() << "\n";

    gWhisper.setTranslationEnabled(translate);
    if (lang != "auto" && !lang.empty()) gWhisper.setLanguageCode(lang);
    gWhisper.setContinuousTranscriptionEnabled(true);
    gWhisper.setPartialTranscriptionsEnabled(stream ? partials : false);
    if (minBufferMs  > 0) gWhisper.setMinBufferMs(minBufferMs);
    if (vadThreshold > 0) gWhisper.setVadThreshold(vadThreshold);
    if (vadHangover  > 0) gWhisper.setVadLenHangover(vadHangover);

    Listener listener;
    listener.setStreaming(stream);
    gWhisper.registerListener(&listener);

    if (stream) {
        InputStream input;
        input.setUseAudioFile(false);
        listener.setEpoch(Clock::now());
        gWhisper.start(&input);
        std::cerr << "streaming: expecting s16le mono 16kHz on stdin\n";

        std::vector<uint8_t> buf(chunkBytes);
        while (!gShutdown) {
            ssize_t n = ::read(STDIN_FILENO, buf.data(), buf.size());
            if (n > 0)       input.write(buf, 0, static_cast<int32_t>(n));
            else if (n == 0) break;                       // stdin closed
            else if (errno == EINTR) continue;
            else { std::cerr << "stdin read error: " << std::strerror(errno) << "\n"; break; }
        }
        input.setStopped(true);
        std::cerr << "stdin closed, draining\n";
        // give the VAD a moment to close and emit the final utterance
        std::this_thread::sleep_for(std::chrono::milliseconds(1500));
        if (gInitialised.exchange(false)) { gWhisper.stop(); gWhisper.deInit(); }
        return 0;
    }

    // One transcription of one file, on the already-initialised session.
    struct Result { bool done; long audioMs, wallMs; std::string text, lang; int err; };
    auto transcribeFile = [&](const std::string& path) -> Result {
        listener.reset();
        InputStream input;
        input.setUseAudioFile(true);
        long audioMs = wavDurationMs(path);
        auto c0 = Clock::now();
        gWhisper.start(&input);
        input.write(path);
        bool done = listener.wait(timeoutMs);
        auto wallMs = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - c0).count();
        gWhisper.stop();
        return Result{done, audioMs, wallMs, listener.text(), listener.lang(), listener.error()};
    };

    if (serveFiles) {
        std::cerr << "serve-files: one wav path per line on stdin\n";
        std::cout << "{\"type\":\"ready\",\"init_ms\":" << initMs << "}\n" << std::flush;
        std::string path;
        while (!gShutdown && std::getline(std::cin, path)) {
            while (!path.empty() && (path.back() == '\r' || path.back() == ' ')) path.pop_back();
            if (path.empty()) continue;
            Result r = transcribeFile(path);
            std::cout << "{\"type\":\"result\""
                      << ",\"file\":\"" << jsonEscape(path) << "\""
                      << ",\"ok\":" << ((r.done && !r.text.empty()) ? "true" : "false")
                      << ",\"text\":\"" << jsonEscape(r.text) << "\""
                      << ",\"language\":\"" << jsonEscape(r.lang) << "\""
                      << ",\"audio_ms\":" << r.audioMs
                      << ",\"wall_ms\":" << r.wallMs
                      << ",\"timeout\":" << (r.done ? "false" : "true")
                      << ",\"err\":" << r.err << "}\n" << std::flush;
        }
        std::cerr << "serve-files: stdin closed\n";
        if (gInitialised.exchange(false)) { gWhisper.stop(); gWhisper.deInit(); }
        return 0;
    }

    std::vector<std::string> clips;
    if (!wavFile.empty()) clips.push_back(wavFile);
    if (!listFile.empty()) {
        std::ifstream f(listFile);
        if (!f) { std::cerr << "cannot read list: " << listFile << "\n"; return 2; }
        std::string line;
        while (std::getline(f, line)) if (!line.empty()) clips.push_back(line);
    }

    std::ofstream fout;
    if (!outFile.empty()) fout.open(outFile);
    std::ostream& out = outFile.empty() ? std::cout : fout;

    int ok = 0, bad = 0;
    for (const auto& clip : clips) {
        if (gShutdown) break;
        Result r = transcribeFile(clip);
        std::string name = clip.substr(clip.find_last_of('/') + 1);
        if (!r.done)            { ++bad; std::cerr << "TIMEOUT " << name << "\n"; }
        else if (r.text.empty()){ ++bad; std::cerr << "EMPTY " << name << " err=" << r.err << "\n"; }
        else                      ++ok;
        out << name << '\t' << r.audioMs << '\t' << r.wallMs << '\t' << r.lang << '\t' << r.text << '\n';
        out.flush();
    }

    std::cerr << "done ok=" << ok << " failed=" << bad << "\n";
    if (gInitialised.exchange(false)) { gWhisper.stop(); gWhisper.deInit(); }
    return (bad > 0 && ok == 0) ? 1 : 0;
}
