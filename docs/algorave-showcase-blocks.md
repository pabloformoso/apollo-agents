# Algorave showcase — bloques para copiar y pegar

Diez patrones Strudel validados con `scripts/algorave-spike/validate.mjs`
(`--key A:minor --genre deep`, 8 ciclos) el 2026-09-22. Todos en **La menor**;
todos menos el último dentro de la valla **deep**. El tempo lo pone el control
BPM de la página (un ciclo = un compás), así que ningún bloque toca `cps`.

Orden sugerido para la grabación: 01 → 02 → 07 → 08 → 09 → 03 → 04 → 06 → 05 → 10.
La primera línea `// reason:` es la que la página muestra como "por qué"; el
Mind la lee cuando coge el lápiz en B2B.

## Apertura · deep house · 122 BPM

```js
// reason: apertura — deep house de manual: 909 a cuatro por cuatro, open hat a contratiempo, bajo rodante en La menor y Am7/Fmaj7 con un colchón de supersaw
stack(
  s("bd*4").bank("RolandTR909").gain(0.95),
  s("[~ oh]*4").bank("RolandTR909").gain(0.5).pan(0.55),
  s("hh*16").bank("RolandTR909").gain("[0.5 0.35 0.42 0.38]*4").swingBy(1/8, 8).pan(0.45),
  s("~ cp ~ cp").bank("RolandTR909").gain(0.6).room(0.3).roomsize(2),
  n("[0 ~] [~ 0] [0 ~] [~ 7] [0 ~] [~ 0] [0 0] [~ 0]").add(n("<0 5>"))
    .scale("A1:minor").s("sawtooth").lpf("<400 500 650 800>").lpq(6)
    .attack(0.005).decay(0.12).sustain(0.35).release(0.08).gain(0.75),
  note("<[a3,c4,e4,g4] [f3,a3,c4,e4]>").struct("~ ~ ~ x ~ ~ ~ x").s("triangle")
    .attack(0.008).decay(0.16).sustain(0.12).release(0.3).lpf(3600).lpq(3)
    .delay(0.4).delaytime(0.1875).delayfeedback(0.32).room(0.55).gain(0.5),
  note("<[a2,e3,g3] [f2,c3,e3]>").s("supersaw").unison(4).detune(0.18)
    .attack(0.6).release(1.2).lpf(sine.range(500, 1600).slow(16)).hpf(120).gain(0.22)
).mul(gain(0.5))
```

## Tech house · 126 BPM

```js
// reason: tech house — bajo a semicorcheas con el filtro respirando cada 8 compases, piano en el "y" de cada tiempo, rim y conga llevando el groove
stack(
  s("bd*4").bank("RolandTR909").gain(0.95),
  s("[~ oh]*4").bank("RolandTR909").gain(0.42),
  s("hh*16").bank("RolandTR909").gain("[0.45 0.25 0.35 0.25]*4").swingBy(1/8, 8),
  s("~ cp ~ cp").bank("RolandTR909").gain(0.55).room(0.2),
  s("[~ rim] [~ ~ rim ~] [~ rim] [rim ~ ~ rim]").bank("RolandTR909").gain(0.45).pan(0.35),
  s("conga").n("<0 1 2 1>").struct("~ ~ x ~ ~ x ~ x").gain(0.4).pan(0.7),
  n("[0 0 ~ 0] [~ 0 0 ~] [0 ~ 0 0] [~ 0 ~ 7]").scale("A1:minor").s("sawtooth")
    .lpf(sine.range(300, 1400).slow(8)).lpq(8).decay(0.1).sustain(0.2).release(0.05).gain(0.8),
  note("<[a3,c4,e4] [g3,c4,e4] [f3,a3,c4] [e3,g3,b3]>").struct("[~ x]*4").s("piano")
    .clip(0.35).hpf(200).room(0.3).gain(0.5)
).mul(gain(0.5))
```

## Techno · 132 BPM

```js
// reason: techno — bombo saturado con rumble debajo, ride y hats a semicorcheas, bajo a contratiempo y un motivo de una nota con delay en corcheas con puntillo
stack(
  s("bd*4").bank("RolandTR909").gain(1).shape(0.3),
  s("bd*4").bank("RolandTR909").lpf(150).room(0.7).roomsize(5).gain(0.5).orbit(2),
  s("hh*16").bank("RolandTR909").gain("[0.6 0.25 0.45 0.25]*4").hpf(4000),
  s("[~ oh]*4").bank("RolandTR909").gain(0.35).hpf(3000),
  s("rd*8").bank("RolandTR909").gain("[0.35 0.2]*4").pan(0.6),
  s("~ cp ~ cp").bank("RolandTR909").gain(0.5).room(0.2),
  s("~ ~ ~ [lt lt ~ mt]").bank("RolandTR909").gain(0.6).mask("<0 0 0 1>"),
  n("[~ 0]*8").scale("A1:minor").s("sawtooth").lpf(450).lpq(4)
    .decay(0.08).sustain(0.15).release(0.03).gain(0.85),
  n("<[0 ~ ~ 0 ~ 0 ~ ~] [~ ~ 0 ~ ~ ~ 3 ~]>").scale("A4:minor").s("square")
    .decay(0.08).sustain(0).lpf(2500).delay(0.5).delaytime(0.375).delayfeedback(0.5)
    .gain(0.35).pan(sine.range(0.3, 0.7).slow(4))
).mul(gain(0.5))
```

## Acid · 128 BPM

```js
// reason: acid — línea 303 en sawtooth con resonancia alta y el corte barriendo 16 compases, un salto de octava aleatorio, batería seca y clap con sala
stack(
  s("bd*4").bank("RolandTR909").gain(0.95),
  s("hh*16").bank("RolandTR909").gain("[0.5 0.2 0.35 0.2]*4"),
  s("[~ oh]*4").bank("RolandTR909").gain(0.4),
  s("~ cp ~ cp").bank("RolandTR909").gain(0.55).room(0.4).roomsize(3),
  s("sh*16").bank("RolandTR808").gain("[0.3 0.15]*8").pan(0.65),
  n("0 0 7 0 3 0 5 [0 7]").sometimesBy(0.2, x => x.add(n(7))).scale("A2:minor").s("sawtooth")
    .lpf(sine.range(200, 2600).slow(16)).lpq(14)
    .attack(0.005).decay(0.15).sustain(0.05).release(0.05).gain(0.7)
).mul(gain(0.5))
```

## Electro 808 · 118 BPM

```js
// reason: electro 808 — bombo largo con un golpe extra en el "y" del cuatro, caja y cowbell del 808, sub en seno y un arpegio en pulse que se invierte cada dos compases
stack(
  s("bd*4").bank("RolandTR808").gain(0.95),
  s("~ ~ ~ [~ ~ bd ~]").bank("RolandTR808").gain(0.7),
  s("~ sd ~ sd").bank("RolandTR808").gain(0.6).room(0.2),
  s("~ cp ~ cp").bank("RolandTR808").gain(0.4),
  s("hh*8").bank("RolandTR808").gain("[0.5 0.3]*4"),
  s("[~ oh]*4").bank("RolandTR808").gain(0.3),
  s("cb ~ ~ cb ~ cb ~ ~").bank("RolandTR808").gain(0.45).pan(0.3),
  n("0 ~ [~ 0] ~ 0 ~ [0 ~] 3").scale("A1:minor").s("sine")
    .decay(0.25).sustain(0.3).release(0.1).gain(0.9),
  n("[0 2 4 7]*2").every(2, x => x.rev()).scale("A4:minor").s("pulse")
    .decay(0.1).sustain(0).lpf(3000).delay(0.3).delaytime(0.25).gain(0.3).pan(0.6)
).mul(gain(0.5))
```

## Dub techno · 120 BPM

```js
// reason: dub techno — acordes Am7/G7 en supersaw con delay largo y el filtro cerrándose, bombo suave, rim a contratiempo que también va al delay y sub en seno
stack(
  s("bd*4").bank("RolandTR909").gain(0.8).lpf(2000),
  s("hh*8").bank("RolandTR909").gain("[0.3 0.2]*4").hpf(5000),
  s("[~ rim]*4").bank("RolandTR909").gain(0.35).pan(0.4).delay(0.3).delaytime(0.375).delayfeedback(0.4),
  s("[~ oh]*4").bank("RolandTR909").gain(0.25).degradeBy(0.5),
  note("<[a2,c3,e3,g3] [g2,b2,d3,f3]>").struct("[~ x ~ ~] [~ ~ x ~] [~ x ~ ~] [~ ~ ~ x]").s("supersaw")
    .unison(3).detune(0.2).attack(0.01).decay(0.3).sustain(0.05).release(0.4)
    .hpf(300).lpf(sine.range(600, 2200).slow(16)).lpq(4)
    .delay(0.7).delaytime(0.375).delayfeedback(0.65).room(0.6).roomsize(6).gain(0.45),
  n("0 ~ ~ ~ 0 ~ [~ 0] ~").scale("A1:minor").s("sine").decay(0.3).sustain(0.4).release(0.2).gain(0.85)
).mul(gain(0.5))
```

## Subida (4 compases) · mismo BPM que lo anterior

```js
// reason: subida — redoble de caja que se dobla cada compás durante cuatro, hats y filtro del bajo abriéndose, crash al empezar: cuatro compases y al drop
stack(
  s("bd*4").bank("RolandTR909").gain(0.95),
  s("cr").bank("RolandTR909").gain(0.6).mask("<1 0 0 0>"),
  s("<sd*4 sd*8 sd*16 sd*32>").bank("RolandTR909").gain(saw.range(0.3, 0.8).slow(4)).room(0.3),
  s("hh*16").bank("RolandTR909").gain(saw.range(0.2, 0.6).slow(4)),
  s("oh*16").bank("RolandTR909").hpf(saw.range(2000, 9000).slow(4)).gain(saw.range(0.1, 0.45).slow(4)),
  n("[~ 0]*8").scale("A1:minor").s("sawtooth").lpf(saw.range(300, 3000).slow(4)).lpq(8)
    .decay(0.1).sustain(0.2).release(0.05).gain(0.8)
).mul(gain(0.5))
```

## Pico · 130 BPM

```js
// reason: pico — todo dentro: riff de supersaw en unísono ancho, bajo a contratiempo, clap doblado con caja, crash cada 8 compases y un pad de sierra debajo
stack(
  s("bd*4").bank("RolandTR909").gain(1).shape(0.2),
  s("~ [cp,sd] ~ [cp,sd]").bank("RolandTR909").gain(0.6).room(0.3),
  s("[~ oh]*4").bank("RolandTR909").gain(0.5),
  s("hh*16").bank("RolandTR909").gain("[0.55 0.3 0.45 0.3]*4"),
  s("cr ~ ~ ~").bank("RolandTR909").gain(0.5).mask("<1 0 0 0 0 0 0 0>"),
  n("[~ 0]*8").scale("A1:minor").s("sawtooth").lpf(600).lpq(5)
    .decay(0.1).sustain(0.2).release(0.05).gain(0.85),
  n("<[0 ~ 3 ~ 5 ~ 3 7] [0 ~ 3 ~ 5 ~ 7 5]>").scale("A3:minor").s("supersaw")
    .unison(5).detune(0.3).spread(0.8).attack(0.01).decay(0.2).sustain(0.1).release(0.2)
    .lpf(sine.range(1200, 4000).slow(8)).hpf(200).delay(0.25).delaytime(0.1875).gain(0.45),
  note("<[a2,c3,e3] [f2,a2,c3]>").s("sawtooth").attack(0.4).release(0.8).lpf(900)
    .unison(2).detune(0.1).gain(0.2)
).mul(gain(0.5))
```

## Respiro (sin bombo) · cualquier BPM

```js
// reason: respiro — fuera la batería: pad de supersaw en Am7/Fmaj7/Dm7/Em7, piano arpegiado con delay y un shaker; para bajar antes de volver a subir
stack(
  s("sh*16").bank("RolandTR808").gain("[0.25 0.12]*8").pan(0.6),
  s("[~ oh]*4").bank("RolandTR909").gain(0.2).hpf(4000),
  note("<[a2,c3,e3,g3] [f2,a2,c3,e3] [d2,f2,a2,c3] [e2,g2,b2,d3]>").s("supersaw").unison(4).detune(0.2)
    .attack(1).release(2).lpf(sine.range(400, 1500).slow(16)).hpf(100).room(0.7).roomsize(6).gain(0.3),
  note("<[a4 c5 e4 g4] [f4 a4 c5 e4] [d4 f4 a4 c5] [e4 g4 b4 d5]>").s("piano").clip(0.8)
    .delay(0.4).delaytime(0.375).delayfeedback(0.45).room(0.5).gain(0.45)
).mul(gain(0.55))
```

## Breaks · 128 BPM · Genre = no fence

```js
// reason: breaks — el amen troceado a semicorcheas por encima del bombo, sub en seno en La menor y hats del 909; requiere Genre = no fence
stack(
  s("bd*4").bank("RolandTR909").gain(0.9),
  s("amencutup").n("0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15").hpf(150).gain(0.6),
  s("hh*8").bank("RolandTR909").gain("[0.4 0.25]*4"),
  s("~ cp ~ cp").bank("RolandTR909").gain(0.5).room(0.3),
  n("0 ~ [~ 0] ~ [0 ~] ~ 3 ~").scale("A1:minor").s("sine").decay(0.3).sustain(0.4).release(0.15).gain(0.9),
  n("<[0 ~ ~ 3 ~ ~ 5 ~] [~ ~ 7 ~ 5 ~ ~ 3]>").scale("A3:minor").s("supersaw").unison(3).detune(0.25)
    .decay(0.15).sustain(0.05).lpf(2500).delay(0.3).delaytime(0.375).gain(0.4)
).mul(gain(0.5))
```

