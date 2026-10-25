$ErrorActionPreference='Stop'
$voice=New-Object -ComObject SAPI.SpVoice
$voice.Voice=$voice.GetVoices() | Where-Object { $_.GetDescription() -eq 'Microsoft Maria Desktop - Portuguese(Brazil)' } | Select-Object -First 1
if (-not $voice.Voice) { throw 'Portuguese voice required' }
$items=Get-Content -LiteralPath $args[0] -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($item in $items) {
  $stream=New-Object -ComObject SAPI.SpFileStream
  $stream.Format.Type=22
  $stream.Open($item.path,3,$false)
  $voice.AudioOutputStream=$stream
  [void]$voice.Speak($item.text)
  $stream.Close()
}
$voice.Voice.GetDescription()
