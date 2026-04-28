import { redirect } from "next/navigation";

// Root "/" redirects authenticated users to /chat; middleware handles unauthenticated redirect to /sign-in
export default function HomePage() {
  redirect("/chat");
}
