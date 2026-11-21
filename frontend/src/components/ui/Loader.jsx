import { LoaderCircle } from 'lucide-react'

export default function Loader({ size = 18 }) {
  return <LoaderCircle className="spin" size={size} aria-hidden="true" />
}
