# CLAUDE.md

Contexto para quem trabalha neste repositório (Claude Code ou pessoa). Ler antes de mexer em código,
macros ou no menu do KlipperScreen. Este ficheiro está em português europeu; o programa, as mensagens e
os outros documentos (`README.md`, `ARCHITECTURE.md`) estão em inglês.

## 1. Objetivo

Programa que põe o Raspberry Pi de uma máquina Klipper em modo **hotspot Wi-Fi**, para o utilizador se
ligar ao Mainsail (browser) numa divisão sem internet. O KlipperScreen corre no ecrã da máquina.

- Para quem: o autor, que constrói máquinas Klipper e as entrega a clientes. Vai instalar isto em cada máquina.
- Porquê: onde a máquina opera não há Wi-Fi nem Ethernet. Com o hotspot, o portátil ou o telemóvel liga-se
  diretamente à máquina e abre `http://10.42.0.1`.
- V1 é pequena de propósito: um modo que se liga e desliga à mão. A estrutura deixa espaço para fallback
  automático, portal de configuração Wi-Fi e QR no ecrã, **mas nada disso está construído**.
- Não faz parte da V1: juntar-se a uma rede Wi-Fi a partir do telemóvel, fallback automático, hotspot e
  rede Wi-Fi do cliente ao mesmo tempo (um rádio, um papel), hotspot com Ethernet como caso suportado,
  5 GHz, WPA3, partilha de internet.

## 2. Ambiente

- Máquinas: Raspberry Pi com MainsailOS 3.0.0 (Debian 13 trixie), Klipper, Moonraker, Mainsail,
  KlipperScreen v0.4.7-196 (versão vista no primeiro ecrã de teste).
- Rede: NetworkManager com `nmcli`. Os perfis Wi-Fi existentes vêm do netplan (`netplan-wlan0-...`).
  O modo partilhado (`ipv4.method shared`) precisa de `dnsmasq`.
- **O adaptador Wi-Fi tem de suportar modo AP.** Verifica com `nmcli -f WIFI-PROPERTIES device show wlan0`
  (tem de dizer `AP: yes`) e `iw list | grep -A10 "Supported interface modes"`.
- Máquinas onde foi visto:
  - Pi 3 sem Wi-Fi integrado, com pen USB Ralink MT7601U: `AP: no`, só `managed` e `monitor`. **Não serve.**
  - Máquina `jntPRO`: `wifi AP mode: supported`, hotspot funcionou. O modelo exato do Pi e da pen não ficou registado.
- Dependências no Klipper (o `install.sh` avisa, mas nunca as instala nem edita o `printer.cfg`):
  - extra `gcode_shell_command`, instalado pelo KIAUH (responder **não** ao exemplo de macro);
  - secção `[respond]` no `printer.cfg` (ou num ficheiro incluído, como o `mainsail.cfg`).
- Python 3.9 ou superior, só biblioteca padrão. Nada para `pip install` nas máquinas.
- Outros projetos do autor usam o mesmo estilo (por exemplo Klipper-IP-Status, pen USB com G-code). Este
  repositório não depende deles.

## 3. Arquitetura

Detalhe em `ARCHITECTURE.md`. Resumo:

```
macro G-code ──► CLI klipper-hotspot ──► socket Unix (JSON) ──► daemon (root) ──► NetworkBackend ──► nmcli
```

| Caminho | Papel |
|---|---|
| `src/klipper_hotspot/api.py` | JSON por linha sobre socket Unix; verbos fixos `on`, `off`, `status`, `credentials`; sem argumentos. |
| `manager.py` | Aplica os verbos através do backend, guarda o estado, serializa com lock. |
| `state.py` | Máquina de estados explícita OFF/ON. Todo o par (estado, evento) tem de estar definido. |
| `policy.py` | Decide quando o hotspot deve estar ligado. V1: `ManualPolicy` (autostart sim/não). |
| `backend.py` | Interface `NetworkBackend` + `NmcliBackend`. **Único** código que toca na rede. Inclui `ap_supported`. |
| `store.py` | Estado persistido (`desired`, `since`). Tolera ficheiro corrompido. |
| `credentials.py` | SSID e palavra-passe por máquina, geradas uma vez, `0600`, nunca em logs. |
| `config.py` | INI estrito e versionado. Secções `[fallback]` e `[portal]` reservadas (ativar dá erro). |
| `doctor.py` | Verificações só de leitura (interface, modo AP, credenciais, daemon, Moonraker, `[respond]`). |
| `notify.py` | Mensagens no ecrã: prompts de ação do Klipper enviados ao Moonraker. Lista branca de caracteres. |
| `cli.py`, `client.py`, `daemon.py`, `errors.py`, `__main__.py` | Ponto de entrada, cliente do socket, processo do daemon, erros. |
| `data/klipper-hotspot.cfg` | Macros `HOTSPOT_ON/OFF/STATUS/CREDENTIALS` + `[gcode_shell_command hotspot_cmd]`. |
| `data/klipperscreen-menu.conf` | Botões dentro de **More → Hotspot** no KlipperScreen. |
| `data/hotspot.conf.example` | Configuração de exemplo (copiada para `/etc/klipper-hotspot/hotspot.conf`). |
| `data/klipper-hotspot.service` | Unidade systemd do daemon. |
| `install.sh`, `uninstall.sh` | Instalação em `/opt/klipper-hotspot`, binário em `/usr/local/bin/klipper-hotspot`. |
| `tests/` | `fakes.py` (FakeBackend, nmcli simulado, Moonraker falso), um ficheiro de teste por módulo. |

Onde fica cada coisa numa máquina: configuração e credenciais em `/etc/klipper-hotspot/`, estado em
`/var/lib/klipper-hotspot/`, socket em `/run/klipper-hotspot/control.sock`, macros em
`~/printer_data/config/klipper-hotspot.cfg`.

## 4. Instalar, atualizar e testar

### Máquina nova (por ordem, por SSH, de preferência com cabo)

1. KIAUH, para o `gcode_shell_command` (antes do include, senão o Klipper para com "not a valid config section"):
   ```
   cd ~ && git clone https://github.com/dw-0/kiauh.git && ./kiauh/kiauh.sh
   ```
   No menu: Advanced → Gcode Shell Command. Exemplo de macro: **não**. Confirmar o caminho do menu no README do KIAUH.
2. Programa:
   ```
   cd ~ && git clone https://github.com/lrafa97/klipper-hotspot
   cd klipper-hotspot && git log -1 --oneline && ./install.sh
   ```
   O instalador gera SSID e palavra-passe únicos desta máquina (para etiqueta).
3. `printer.cfg`: acrescentar `[respond]` (se não existir) e `[include klipper-hotspot.cfg]`, depois **RESTART** no Klipper.
4. `KlipperScreen.conf`: colar o conteúdo de `data/klipperscreen-menu.conf` acima do bloco `#~#` gerado
   automaticamente (esse bloco não se toca), depois `sudo systemctl restart KlipperScreen`.
5. `sudo klipper-hotspot doctor`. Tudo `[OK  ]`, em especial `wifi AP mode`.
6. Testar: `HOTSPOT_STATUS` primeiro, depois `HOTSPOT_ON`, ligar o telemóvel ao SSID, abrir `http://10.42.0.1`, `HOTSPOT_OFF`.

### Atualizar

```
cd ~/klipper-hotspot && git pull && git log -1 --oneline && ./install.sh
```
Depois **RESTART** no Klipper (as macros mudam). O `install.sh` **não** atualiza o `KlipperScreen.conf`: se o
menu mudou, é preciso substituir o bloco à mão. Não há atualização automática (a integração com o
`update_manager` do Moonraker ficou de fora porque o instalador precisa de root).

### Testes

```
python3 -m pytest -q          # 182 passam, 8 ficam saltados (hardware)
sudo HOTSPOT_HW_TESTS=1 python3 -m pytest -m hardware   # só num Pi com NetworkManager
```
- Os testes de hardware cortam o Wi-Fi: correr por cabo Ethernet ou no ecrã, nunca só por Wi-Fi. **Ainda não foram corridos.**
- O nmcli simulado codifica as nossas suposições sobre o formato do nmcli. Só os testes de hardware as confirmam.
- O `doctor` corre-se com `sudo` (o ficheiro de credenciais é `0600 root`).
- Precisa de hardware real: NetworkManager de verdade, modo AP do adaptador, o ecrã do KlipperScreen, o
  Windows/iOS/Android a ligar-se, o regresso à rede normal depois de `HOTSPOT_OFF`.

## 5. Decisões técnicas

1. **Hotspot é um modo manual**, `autostart` desligado por omissão. Alternativa rejeitada: ligar sozinho ao
   arranque; uma máquina que se ligasse sozinha ao hotspot deixava de estar na rede do cliente.
2. **Sem caso suportado de hotspot + Ethernet em simultâneo.** Decisão do utilizador.
3. **Um rádio, um papel.** Hotspot e ligação à rede do cliente não coexistem na mesma antena. Aceite.
4. **Python 3.9+ só com biblioteca padrão.** Nada a instalar nas máquinas.
5. **Programa, macros, mensagens e documentos em inglês.** Decisão tomada também no Klipper-IP-Status.
6. **Controlo por socket Unix e não pelo Moonraker**, para o daemon funcionar com o Klipper ou o Moonraker em baixo e todos os clientes serem iguais.
7. **`nmcli` por subprocesso e não D-Bus**: mais fácil de depurar numa máquina no terreno.
8. **`status` nunca mostra a palavra-passe**; `credentials` é a única forma explícita de a ler.
9. **O perfil NetworkManager tem `autoconnect no` e é apagado no `off`.** Um reboot nunca revive o hotspot, e a palavra-passe não fica no NetworkManager.
10. **Credenciais únicas por máquina** (`secrets`, sem caracteres ambíguos 0/o/1/l/i). Nunca partilhar uma palavra-passe entre máquinas de clientes. Criar recusa-se a sobrescrever.
11. **Mensagens no ecrã com prompts de ação do Klipper** (`RESPOND TYPE=command MSG="action:prompt_*"`) enviados ao Moonraker em loopback, sem proxy. Alternativa rejeitada: colocar um painel próprio no KlipperScreen (muito mais manutenção).
12. **Tudo o que entra numa linha de G-code passa por uma lista branca** de caracteres (`notify.clean`), porque mensagens de erro do nmcli podem ter texto arbitrário. O apóstrofo é permitido, a aspa dupla nunca.
13. **O menu do KlipperScreen só aparece se a macro existir** (`enable:` testa `printer.gcode_macros.list`): sem o include, não há botão, em vez de um botão que falha.
14. **O `install.sh` nunca edita `printer.cfg` nem `KlipperScreen.conf`**; só avisa. Esses ficheiros são do utilizador.
15. **Recusar cedo quando o adaptador não tem AP** (`ap_unsupported`), em vez de deixar o nmcli dar o erro críptico.
16. **Seams só com implementação real**: nada de marcadores para funcionalidades que ninguém consegue especificar ainda.

## 6. Não repetir (o que falhou e como se resolveu)

- `Section 'gcode_shell_command hotspot_cmd' is not a valid config section` e o Klipper pára: faltava a extensão. Instalar pelo KIAUH **antes** do include.
- KlipperScreen "Invalid config file": comentário com `[...]` no `klipperscreen-menu.conf`. **Nenhuma linha de comentário pode ter colchetes.** Há teste (`test_only_section_headers_contain_square_brackets`).
- `panel: menu` não está na documentação e `panel` desativa `method`/`params`/`confirm`. Não usar.
- O KlipperScreen mostra **só o último `prompt_text`**. Todas as linhas vão num único texto, juntas com ` - `. Há teste.
- Um `prompt_show` novo é ignorado enquanto houver um diálogo aberto: fechar um antes de carregar noutro botão.
- Mensagens de erro cortadas a 80 e depois a 200 caracteres escondiam o motivo. Limites atuais: 400 por linha e 500 por prompt.
- Push com um teste a falhar: o código de saída do `pytest` foi escondido por `| tail`. **Só fazer push se o `pytest` devolver 0**, guardando o `rc` antes de qualquer pipe.
- Um teste do bypass de proxy passava por engano porque `NO_PROXY` escondia o erro. Os testes têm de poder falhar.
- `RESPOND` e prompts precisam de `[respond]`. O `doctor` verifica.
- `nmcli` dizia só "profile is not compatible with device" quando o adaptador não faz AP (`AP: no`). Resolvido com `ap_supported` + check no `doctor` + aviso no `install.sh`. Hardware sem AP não se resolve por software.
- `doctor` sem `sudo` dizia "credentials ... is malformed" quando na verdade não conseguia ler o ficheiro. Agora diz "permission denied (run with sudo)". **Não apagar credenciais para resolver isto**: gera uma palavra-passe nova e invalida etiquetas.
- "Atualizei e não mudou nada": o `git pull` não chega. Falta `./install.sh` (código em `/opt`), o RESTART do Klipper (macros) e substituir o bloco no `KlipperScreen.conf` (menu). Um clone antigo em `~/klipper-hotspot` faz o `git clone` falhar com "already exists"; usar `git pull`.
- O botão tinha de estar em **More**, não no ecrã principal (pedido do utilizador): sec. `menu __main more hotspot`. O More é definido pelo próprio KlipperScreen.
- O Windows pode mostrar um campo de PIN (4 a 8 dígitos) ao ligar ao hotspot. Não é a palavra-passe errada: escolher "Ligar com uma chave de segurança". Com essa opção funcionou.
- `NO_PROXY`/proxies: o Moonraker é sempre acedido em loopback e sem proxy (`ProxyHandler({})`).

## 7. Convenções

- **Idioma com o autor:** português europeu. Respostas diretas e honestas, sem frases de graxa nem introduções;
  a primeira linha é o mais útil; se ele estiver errado, dizê-lo e explicar porquê. Mudar de posição só com
  informação nova.
- **Configuração, hardware e segurança:** dizer sempre o que foi assumido e o que confirmar na documentação oficial. Nas outras respostas, avisar só quando for palpite.
- **Programa, macros, mensagens ao utilizador, comentários e docs do repositório:** inglês.
- **Commits:** uma linha no imperativo, em inglês, a dizer o que muda e, se ajudar, porquê (ex.: `Detect Wi-Fi adapters without AP mode: clear error, doctor check, installer warning`). Terminar com as linhas de atribuição indicadas pela sessão.
- **Push:** só depois de `python3 -m pytest -q` devolver 0, e sem esconder o código de saída num pipe.
- **Mudanças que o utilizador vai colar numa máquina** (menu, macros): testar também a consistência entre macros, menu e verbos (`tests/test_klipper_files.py`).
- **Não alterar o bloco `#~#` do `KlipperScreen.conf` do utilizador**, nem mexer no `printer.cfg` dele.
- **Testes:** cada bug visto numa máquina real ganha um teste que falha sem a correção; verificar com uma mutação rápida numa cópia.
- **Segredos:** a palavra-passe nunca entra em `status`, logs, mensagens de erro nem commits. O `HOTSPOT_CREDENTIALS` e o diálogo do `HOTSPOT_ON` mostram-na no ecrã/consola: não colar capturas dessas no suporte.
- **Antes de pedir comandos ao utilizador:** dar a lista toda por ordem, para colar de seguida, e dizer onde correr (SSH, consola do Mainsail, ecrã). Pedir sempre a saída do `sudo klipper-hotspot doctor` e do `git log -1 --oneline` para saber que versão corre.

## 8. Estado

Versão `0.1.0`. Último estado registado: 182 testes a passar, 8 saltados (hardware).

**Feito e confirmado numa máquina real**
- Instalação, macros no Mainsail, botões em More → Hotspot no KlipperScreen (v0.4.7-196).
- Diálogos no ecrã: Status, erros e o diálogo do `HOTSPOT_ON` com SSID, palavra-passe e endereço.
- Hotspot a ligar, portátil Windows a ligar-se, Mainsail a abrir em `http://10.42.0.1`.
- Deteção de adaptador sem AP (visto no Pi 3 com MT7601U): erro claro, `doctor` e aviso no instalador.
- `doctor` com `sudo`: mensagem correta quando não consegue ler as credenciais.

**Por fazer / não confirmado**
- `HOTSPOT_OFF`: confirmar que a máquina volta sozinha à rede normal e quanto demora.
- Testes de hardware (`HOTSPOT_HW_TESTS=1`) nunca corridos num Pi.
- Moonraker com logins forçados (o comando funciona e avisa, mas não foi visto).
- iOS e Android a ligar ao hotspot; telemóveis a manterem a rede sem internet.
- Regulatory domain (país Wi-Fi) definido nas máquinas.
- Licença do repositório: nenhuma escolhida. Decidir se o repositório fica privado ou público.
- Funcionalidades previstas e **não construídas**: QR no ecrã, fallback automático, portal de Wi-Fi, rotação de palavra-passe, perfil por keyfile em vez de palavra-passe na linha de comandos.

**Problemas conhecidos**
- A palavra-passe fica visível na lista de processos durante a chamada `nmcli connection add ... psk` (trade-off aceite; o backend permite trocar por keyfile).
- A palavra-passe passa pelo histórico de G-code do Klipper e pela consola do Moonraker quando é mostrada no ecrã.
- Sem NTP em modo hotspot: relógio impreciso sem RTC (o Pi 5 tem bateria de RTC opcional).
- Em Pi 3 sem Wi-Fi integrado, tudo depende de uma pen com AP. Se se escolher outra, confirmar o chipset e o driver Linux em modo AP, e depois `iw list`.
