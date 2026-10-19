// Composition root: wires features together. Later features add routing and
// the HTTP adapter from @ideology-app/core here.
import { HomePage } from "../features/home/HomePage";

export function App() {
  return <HomePage />;
}
