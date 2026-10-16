cmake_minimum_required(VERSION 3.8.0 FATAL_ERROR)
project(whisper-npu-host CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_compile_options(-O2 -Wall -Wextra -fPIC)

# Qualcomm VoiceAI ASR whisper_sdk. Proprietary, so it is not in the repo:
#   cmake -S . -B build -DVOICEAI_SDK=/data/spectra/vendor/voiceai_asr/2.3.0.0/whisper_sdk
set(VOICEAI_SDK "" CACHE PATH "Path to the VoiceAI ASR whisper_sdk directory")
if(NOT VOICEAI_SDK OR NOT EXISTS "${VOICEAI_SDK}/include/npu/rpc/linux/Whisper.h")
    message(FATAL_ERROR "Set -DVOICEAI_SDK to the whisper_sdk directory (Whisper.h not found)")
endif()
set(SDKLIB "${VOICEAI_SDK}/libs/npu/rpc_libraries/linux/whisper_all_quantized")

include_directories("${VOICEAI_SDK}/include/npu/rpc/linux")

add_executable(whisper-npu-host src/main.cpp)
target_link_libraries(whisper-npu-host
    "${SDKLIB}/libwhisperfunction.so"
    "${SDKLIB}/libwhisper_lib.so"
    "${SDKLIB}/libdnnvad.so"
    "${SDKLIB}/libeai_floating.so"
    "${SDKLIB}/libfft.so"
    pthread
)

install(TARGETS whisper-npu-host RUNTIME DESTINATION bin)
