// Захват звука созвона двумя раздельными потоками: системный звук (собеседник в Meet)
// и микрофон (я). Звук никуда не отправляется — только в stdout этому же компьютеру.
//
// Формат stdout — пакеты подряд:
//   1 байт   канал: 'S' системный звук, 'M' микрофон
//   Float64  время начала пакета в секундах (общие часы для обоих каналов)
//   UInt32   число сэмплов
//   Int16[]  сэмплы, 16 кГц, моно
// Сообщения для человека — в stderr.
//
// Собирается скриптом scripts/live-transcribe.py. Нужны разрешения macOS для приложения,
// из которого запущено (Терминал): «Запись экрана и системного звука» и «Микрофон».

import AVFoundation
import ScreenCaptureKit

let outFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true)!
let writeQueue = DispatchQueue(label: "write")

func log(_ text: String) {
    FileHandle.standardError.write((text + "\n").data(using: .utf8)!)
}

final class Channel {
    let tag: UInt8
    private var converter: AVAudioConverter?
    private var inFormat: AVAudioFormat?

    init(_ tag: Character) { self.tag = tag.asciiValue! }

    func handle(_ sample: CMSampleBuffer) {
        guard sample.isValid, sample.numSamples > 0,
              var description = sample.formatDescription?.audioStreamBasicDescription,
              let format = AVAudioFormat(streamDescription: &description) else { return }
        if converter == nil || inFormat != format {
            converter = AVAudioConverter(from: format, to: outFormat)
            inFormat = format
            log("capture: канал \(Character(UnicodeScalar(tag))) — \(Int(format.sampleRate)) Гц, каналов: \(format.channelCount)")
        }
        guard let converter else { return }
        try? sample.withAudioBufferList { list, _ in
            guard let input = AVAudioPCMBuffer(pcmFormat: format, bufferListNoCopy: list.unsafePointer) else { return }
            let capacity = AVAudioFrameCount(Double(input.frameLength) * outFormat.sampleRate / format.sampleRate) + 64
            guard let output = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: capacity) else { return }
            var fed = false
            var error: NSError?
            converter.convert(to: output, error: &error) { _, status in
                if fed {
                    status.pointee = .noDataNow
                    return nil
                }
                fed = true
                status.pointee = .haveData
                return input
            }
            guard error == nil, output.frameLength > 0, let samples = output.int16ChannelData?[0] else { return }
            var packet = Data([tag])
            var time = sample.presentationTimeStamp.seconds
            var count = UInt32(output.frameLength)
            packet.append(Data(bytes: &time, count: 8))
            packet.append(Data(bytes: &count, count: 4))
            packet.append(Data(bytes: samples, count: Int(count) * 2))
            writeQueue.async {
                do { try FileHandle.standardOutput.write(contentsOf: packet) } catch { exit(0) }  // читатель закрылся
            }
        }
    }
}

final class Capture: NSObject, SCStreamOutput, SCStreamDelegate {
    private let system = Channel("S")
    private let microphone = Channel("M")
    private var stream: SCStream?

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else {
            throw NSError(domain: "capture", code: 1, userInfo: [NSLocalizedDescriptionKey: "не найден экран"])
        }
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.captureMicrophone = true
        config.sampleRate = 48_000
        config.channelCount = 1
        // Картинка не нужна, но поток без неё не создать: берём 2×2 пикселя раз в секунду.
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)

        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        let stream = SCStream(filter: filter, configuration: config, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: DispatchQueue(label: "system"))
        try stream.addStreamOutput(self, type: .microphone, sampleHandlerQueue: DispatchQueue(label: "microphone"))
        try await stream.startCapture()
        self.stream = stream
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        switch type {
        case .audio: system.handle(sample)
        case .microphone: microphone.handle(sample)
        default: break
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        log("capture: поток остановлен — \(error.localizedDescription)")
        exit(1)
    }
}

signal(SIGPIPE, SIG_IGN)
signal(SIGINT, SIG_IGN)
signal(SIGTERM, SIG_IGN)
let stopSources = [SIGINT, SIGTERM].map { number in
    let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
    source.setEventHandler { exit(0) }
    source.resume()
    return source
}

let capture = Capture()
Task {
    if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined {
        _ = await AVCaptureDevice.requestAccess(for: .audio)
    }
    if AVCaptureDevice.authorizationStatus(for: .audio) != .authorized {
        log("capture: нет доступа к микрофону. Системные настройки → Конфиденциальность и безопасность → Микрофон — включить для приложения, из которого запущен скрипт.")
        exit(3)
    }
    do {
        try await capture.start()
        log("capture: идёт захват — системный звук и микрофон")
    } catch {
        log("capture: не удалось начать захват — \(error.localizedDescription)")
        log("capture: Системные настройки → Конфиденциальность и безопасность → Запись экрана и системного звука — включить для приложения, из которого запущен скрипт, и перезапустить его.")
        exit(2)
    }
}
dispatchMain()
